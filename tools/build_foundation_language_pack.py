'''Offline V73 corpus-grounded foundation language pack builder.

Reads an original kgpack, a canonical supervised corpus and a proposal. It derives
every compositional frame pattern again from the corpus text and annotated spans,
and checks that the proposal equals that derivation. It then publishes a new pack
exclusively, without overwriting anything. In that pack the language graph gains
V73 rules after the original rules. Every other member stays byte-identical.
Nothing runs at import time.
'''
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
import zipfile

__all__ = ['FoundationBuildError', 'build_foundation_language_pack']

_MAX_JSON_BYTES = 1048576
_MAX_GRAMMAR_BYTES = 65536
_MAX_PACK_BYTES = 1 << 28
_ROWS = 300
_MAX_UNITS = 4096
_MAX_ENTRIES = 12
_MAX_MODIFIERS = 8
_TEXT_CHARS = 256
_UNIT_IDS_PER_ROW = 16
_MAX_DEPTH = 32
_HEAD_CAP = 128
_LITERAL_CAP = 64
_MIN_PAIRS = 3
_ORIGINAL_HEAD = '[가-힣A-Za-z][가-힣A-Za-z0-9_]*'
_GRAPH_MEMBER = 'graphs/korean-executable-seed.kg'
_CORPUS_SCHEMA = 'marco-foundation-language-corpus-v1'
_PROPOSAL_SCHEMA = 'marco-foundation-language-proposal-v1'
_RELATIONS = ('seed_owns', 'seed_located_in')
_ENDINGS = ('plain', 'informal', 'polite', 'formal')
_STEMS = ('있', '없')
_KINDS = ('existential',)
_UNIT_KINDS = ('lexical', 'inflection', 'particle', 'nounphrase_modifier', 'word_order')
_ENTRY_KEYS = ('id', 'family', 'source_sentence_ids', 'source_unit_ids', 'relation', 'polarity',
               'modality', 'order', 'segments', 'inflection')
_SCOPE = 'finite_supervised_corpus_graph_augmentation'
_PREFIX = 'v73_'
_SHA_RE = re.compile('[0-9a-f]{64}')
_ID_RE = re.compile('[A-Za-z0-9_.:-]{1,128}')
_PRED_RE = re.compile('[가-힣]+(?: [가-힣]+)*')
_MOD_RE = re.compile('[가-힣]{1,16}')
_HEAD_RE = re.compile(_ORIGINAL_HEAD)
_LF = chr(10)
_UNSAFE_CHARS = (chr(34), '|', '#', chr(10), chr(13))


class FoundationBuildError(ValueError):
    '''The inputs are refused; nothing is published.'''


def _fail(message):
    raise FoundationBuildError(message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                       allow_nan=False) + _LF).encode('utf-8')


# --- paths and bounded reads ---------------------------------------------------------

def _path(value, label):
    try:
        raw = os.fspath(value)
    except TypeError:
        _fail('%s is not a path' % label)
    if not isinstance(raw, str) or not raw or chr(0) in raw:
        _fail('%s is not a usable path' % label)
    path = os.path.abspath(raw)
    probe = path
    while True:
        if os.path.islink(probe):
            _fail('%s: symlink in path refused' % label)
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return path


def _read_bounded(path, cap, label):
    if not os.path.isfile(path):
        _fail('%s is not a regular file' % label)
    with open(path, 'rb') as fh:
        data = fh.read(cap + 1)
    if len(data) > cap:
        _fail('%s exceeds %d bytes' % (label, cap))
    return data


# --- strict JSON ---------------------------------------------------------------------

def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            _fail('duplicate JSON key %r' % key)
        out[key] = value
    return out


def _refuse_constant(name):
    _fail('non-finite JSON constant %r' % name)


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        _fail('non-finite JSON number')
    return value


def _walk(value, depth):
    if depth > _MAX_DEPTH:
        _fail('JSON nesting exceeds %d' % _MAX_DEPTH)
    kind = type(value)
    if value is None or kind is bool or kind is int or kind is str:
        return
    if kind is float:
        if not math.isfinite(value):
            _fail('non-finite JSON number')
        return
    if kind is list:
        for item in value:
            _walk(item, depth + 1)
        return
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail('JSON key is not a string')
            _walk(item, depth + 1)
        return
    _fail('unsupported JSON value type')


def _load_json(data, label, canonical):
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        _fail('%s is not UTF-8' % label)
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_refuse_constant,
                           parse_float=_finite_float)
    except FoundationBuildError:
        raise
    except (ValueError, RecursionError) as exc:
        raise FoundationBuildError('%s is not valid JSON' % label) from exc
    _walk(value, 0)
    if canonical and _canonical(value) != data:
        _fail('%s bytes are not canonical' % label)
    return value


# --- shape helpers -------------------------------------------------------------------

def _exact(obj, keys, label, optional=()):
    if type(obj) is not dict:
        _fail('%s must be an object' % label)
    have = set(obj)
    if not set(keys) <= have or not have <= set(keys) | set(optional):
        _fail('%s has wrong keys' % label)


def _text(value, label, cap=_TEXT_CHARS):
    if type(value) is not str or not value or len(value) > cap:
        _fail('%s must be a nonempty string of at most %d chars' % (label, cap))
    return value


def _ident(value, label):
    if type(value) is not str or not _ID_RE.fullmatch(value):
        _fail('%s is not a safe identifier' % label)
    return value


def _id_list(value, label, cap):
    if type(value) is not list or len(value) > cap:
        _fail('%s must be a list of at most %d ids' % (label, cap))
    for item in value:
        _ident(item, label)
    if len(set(value)) != len(value):
        _fail('%s repeats an id' % label)
    return value


def _span(value, length, label):
    if (type(value) is not list or len(value) != 2 or any(type(v) is not int for v in value)
            or not 0 <= value[0] < value[1] <= length):
        _fail('%s is not a valid span' % label)
    return (value[0], value[1])


def _inflection(value, parsing_endings, kinds):
    if value is None:
        return None
    _exact(value, ('stem', 'kind', 'endings', 'canonical_ending'), 'inflection')
    if value['stem'] not in _STEMS or type(value['stem']) is not str:
        _fail('inflection stem is outside the safe existential stems')
    if type(value['kind']) is not str or value['kind'] not in _KINDS or value['kind'] not in kinds:
        _fail('inflection kind is not allowed')
    endings = value['endings']
    if (type(endings) is not list or not endings or len(set(endings)) != len(endings)
            or any(type(e) is not str or e not in _ENDINGS or e not in parsing_endings for e in endings)):
        _fail('inflection endings are not an allowed existing subset')
    if value['canonical_ending'] != 'plain' or 'plain' not in endings:
        _fail('inflection canonical ending must be plain')
    return value


def _safe_scalar(value):
    if type(value) is not str or not value or len(value) > 512:
        _fail('graph scalar must be a nonempty bounded string')
    for ch in _UNSAFE_CHARS:
        if ch in value:
            _fail('graph scalar holds an unwritable character')


# --- corpus derivation ---------------------------------------------------------------

def _row(s, unit_by_id):
    _exact(s, ('id', 'text', 'entry_id', 'slots', 'slot_spans', 'predicate_span', 'meaning', 'unit_ids'),
           'sentence')
    sid = _ident(s['id'], 'sentence id')
    text = _text(s['text'], 'sentence text')
    _text(s['entry_id'], 'sentence seed provenance')
    slots, spans, meaning = s['slots'], s['slot_spans'], s['meaning']
    _exact(slots, ('subject', 'object'), 'slots')
    _exact(spans, ('subject', 'object'), 'slot_spans')
    _exact(meaning, ('triple', 'polarity', 'modality'), 'meaning')
    n = len(text)
    subj = _span(spans['subject'], n, 'subject span')
    obj = _span(spans['object'], n, 'object span')
    pred = _span(s['predicate_span'], n, 'predicate span')
    if pred[1] != n:
        _fail('predicate span must end the text: %s' % sid)
    ordered = sorted([(subj, 'subject'), (obj, 'object'), (pred, None)], key=lambda x: x[0][0])
    for left, right in zip(ordered, ordered[1:]):
        if left[0][1] > right[0][0]:
            _fail('spans overlap: %s' % sid)
    values = {}
    for role, sp in (('subject', subj), ('object', obj)):
        value = _text(slots[role], 'slot value')
        if text[sp[0]:sp[1]] != value:
            _fail('slot span does not equal slot value: %s' % sid)
        values[role] = value
    triple = meaning['triple']
    if (type(triple) is not list or len(triple) != 3 or triple[0] != values['subject']
            or triple[2] != values['object'] or type(triple[1]) is not str or triple[1] not in _RELATIONS):
        _fail('meaning triple is not bound to the slots: %s' % sid)
    relation = triple[1]
    polarity = meaning['polarity']
    if type(polarity) is not bool or meaning['modality'] != 'asserted':
        _fail('meaning polarity/modality invalid: %s' % sid)
    unit_ids = _id_list(s['unit_ids'], 'sentence unit ids', _UNIT_IDS_PER_ROW)
    row_units = []
    for uid in unit_ids:
        if uid not in unit_by_id:
            _fail('sentence names an unknown unit: %s' % sid)
        row_units.append(unit_by_id[uid])
    lexical = [u for u in row_units if u['kind'] == 'lexical']
    if len(lexical) != 1:
        _fail('sentence needs exactly one lexical predicate unit: %s' % sid)
    lex = lexical[0]
    form = text[pred[0]:pred[1]]
    if lex['form'] != form or not _PRED_RE.fullmatch(form):
        _fail('predicate span does not equal the lexical unit form: %s' % sid)
    meta = lex['meaning_metadata']
    if meta['relation'] != relation or meta['polarity'] is not polarity:
        _fail('lexical metadata disagrees with sentence meaning: %s' % sid)
    hits = []
    at = text.find(form)
    while at >= 0:
        if all(at + len(form) <= sp[0] or sp[1] <= at for sp in (subj, obj)):
            hits.append(at)
        at = text.find(form, at + 1)
    if hits != [pred[0]]:
        _fail('predicate position is ambiguous: %s' % sid)
    infl = meta['inflection']
    if infl is not None and not form.endswith(infl['stem'] + '다'):
        _fail('inflection stem does not derive the canonical predicate tail: %s' % sid)
    for u in row_units:
        if u['kind'] in ('lexical', 'nounphrase_modifier') and u['form'] not in text:
            _fail('unit form does not occur in its source sentence: %s' % sid)
    row_mods = [u for u in row_units if u['kind'] == 'nounphrase_modifier']
    used = set()
    uses = []
    cores = []
    for role in ('subject', 'object'):
        value = values[role]
        found = [u for u in row_mods if value.startswith(u['form'] + ' ')]
        if len(found) > 1:
            _fail('slot has several modifiers: %s' % sid)
        core = value
        if found:
            core = value[len(found[0]['form']) + 1:]
            used.add(found[0]['id'])
            uses.append((found[0]['form'], found[0]['id']))
        if not _HEAD_RE.fullmatch(core):
            _fail('slot head is outside the original head pattern: %s' % sid)
        cores.append(core)
    if used != {u['id'] for u in row_mods}:
        _fail('declared modifier unit is not used by a slot: %s' % sid)
    segments = []
    cursor = 0
    for sp, role in ordered:
        if sp[0] > cursor:
            literal = text[cursor:sp[0]]
            if len(literal) > _LITERAL_CAP:
                _fail('literal segment too long: %s' % sid)
            segments.append({'literal': literal})
        segments.append({'slot': role} if role is not None else {'predicate': form})
        cursor = sp[1]
    order = ['subject', 'object'] if subj[0] < obj[0] else ['object', 'subject']
    signature = {'segments': segments, 'relation': relation, 'polarity': polarity,
                 'modality': 'asserted', 'inflection': copy.deepcopy(infl)}
    return {'id': sid, 'text': text, 'signature': signature, 'order': order,
            'pair': (values['subject'], values['object']), 'units': set(unit_ids),
            'lexical': lex['id'], 'cores': cores, 'uses': uses}


def _norm_segments(value):
    if type(value) is not list or not 3 <= len(value) <= 16:
        _fail('entry segments must be a short list')
    out = []
    for seg in value:
        if type(seg) is not dict or len(seg) != 1:
            _fail('segment must be a one-key object')
        (key, item), = seg.items()
        if key == 'literal':
            _text(item, 'literal segment', _LITERAL_CAP)
            if out and 'literal' in out[-1]:
                out[-1] = {'literal': out[-1]['literal'] + item}
            else:
                out.append({'literal': item})
        elif key == 'slot' and item in ('subject', 'object') and type(item) is str:
            out.append({'slot': item})
        elif key == 'predicate':
            _text(item, 'predicate segment')
            out.append({'predicate': item})
        else:
            _fail('unknown segment kind')
    if (sum(1 for s in out if 'predicate' in s) != 1
            or sorted(s['slot'] for s in out if 'slot' in s) != ['object', 'subject']):
        _fail('segments need two distinct slots and one predicate')
    return out


def _norm_modifiers(value, label):
    if type(value) is not list or len(value) > _MAX_MODIFIERS:
        _fail('%s must list at most %d modifiers' % (label, _MAX_MODIFIERS))
    out = {}
    for item in value:
        _exact(item, ('text', 'source_sentence_ids', 'source_unit_ids'), label)
        text = _text(item['text'], 'modifier text', 16)
        if not _MOD_RE.fullmatch(text) or text in out:
            _fail('%s modifier text invalid or repeated' % label)
        out[text] = (frozenset(_id_list(item['source_sentence_ids'], 'modifier sentence ids', _ROWS)),
                     frozenset(_id_list(item['source_unit_ids'], 'modifier unit ids', _MAX_UNITS)))
    return out


def _derive(corpus, proposal, source_sha, parsing_endings, kinds):
    _exact(corpus, ('schema', 'sentences', 'units', 'source_pack_sha256', 'modifier_terms'), 'corpus',
           ('candidate_entries',))
    _exact(proposal, ('schema', 'corpus_sha256', 'entries', 'modifier_terms', 'source_pack_sha256'),
           'proposal')
    if corpus['schema'] != _CORPUS_SCHEMA or proposal['schema'] != _PROPOSAL_SCHEMA:
        _fail('corpus/proposal schema mismatch')
    if corpus['source_pack_sha256'] != source_sha or proposal['source_pack_sha256'] != source_sha:
        _fail('source pack sha256 mismatch')
    units = corpus['units']
    if type(units) is not list or not units or len(units) > _MAX_UNITS:
        _fail('corpus units invalid')
    unit_by_id = {}
    for u in units:
        _exact(u, ('id', 'kind', 'form', 'meaning_metadata', 'source_sentence_ids'), 'unit')
        uid = _ident(u['id'], 'unit id')
        if uid in unit_by_id:
            _fail('unit id repeats')
        if type(u['kind']) is not str or u['kind'] not in _UNIT_KINDS:
            _fail('unit kind invalid')
        _text(u['form'], 'unit form')
        meta = u['meaning_metadata']
        if type(meta) is not dict:
            _fail('unit meaning_metadata must be an object')
        if u['kind'] == 'lexical':
            _exact(meta, ('relation', 'polarity', 'modality', 'inflection'), 'lexical metadata')
            if (type(meta['relation']) is not str or meta['relation'] not in _RELATIONS
                    or type(meta['polarity']) is not bool or meta['modality'] != 'asserted'):
                _fail('lexical metadata invalid')
            _inflection(meta['inflection'], parsing_endings, kinds)
        if u['kind'] == 'nounphrase_modifier' and not _MOD_RE.fullmatch(u['form']):
            _fail('modifier unit form invalid')
        _id_list(u['source_sentence_ids'], 'unit source ids', _ROWS)
        unit_by_id[uid] = u
    sentences = corpus['sentences']
    if type(sentences) is not list or len(sentences) != _ROWS:
        _fail('corpus must hold exactly %d sentences' % _ROWS)
    membership = {uid: set() for uid in unit_by_id}
    seen_ids, texts = set(), set()
    groups = {}
    modifiers = {}
    cores = set()
    for s in sentences:
        row = _row(s, unit_by_id)
        if row['id'] in seen_ids or row['text'] in texts:
            _fail('sentence id or text repeats')
        seen_ids.add(row['id'])
        texts.add(row['text'])
        for uid in row['units']:
            membership[uid].add(row['id'])
        cores.update(row['cores'])
        for form, uid in row['uses']:
            slot = modifiers.setdefault(form, (set(), set()))
            slot[0].add(row['id'])
            slot[1].add(uid)
        key = _canonical(row['signature'])
        group = groups.setdefault(key, {'sig': row['signature'], 'order': row['order'], 'rows': set(),
                                        'pairs': set(), 'units': set(), 'lexical': set()})
        if group['order'] != row['order']:
            _fail('grouped order disagrees')
        group['rows'].add(row['id'])
        group['pairs'].add(row['pair'])
        group['units'].update(row['units'])
        group['lexical'].add(row['lexical'])
    for uid, unit in unit_by_id.items():
        if set(unit['source_sentence_ids']) != membership[uid]:
            _fail('unit source ids are not the inverse of sentence unit ids: %s' % uid)
    qualifying = {k: g for k, g in groups.items() if len(g['pairs']) >= _MIN_PAIRS}
    if not qualifying or len(qualifying) > _MAX_ENTRIES:
        _fail('derived pattern count outside 1..%d' % _MAX_ENTRIES)
    entries = proposal['entries']
    if type(entries) is not list or len(entries) > _MAX_ENTRIES:
        _fail('proposal entries invalid')
    matched = {}
    ids = set()
    for e in entries:
        _exact(e, _ENTRY_KEYS, 'entry')
        eid = _ident(e['id'], 'entry id')
        if eid in ids:
            _fail('entry id repeats')
        ids.add(eid)
        _text(e['family'], 'entry family', 64)
        if (type(e['polarity']) is not bool or type(e['relation']) is not str
                or e['relation'] not in _RELATIONS or e['modality'] != 'asserted'):
            _fail('entry meaning invalid')
        infl = _inflection(e['inflection'], parsing_endings, kinds)
        sig = {'segments': _norm_segments(e['segments']), 'relation': e['relation'],
               'polarity': e['polarity'], 'modality': 'asserted', 'inflection': infl}
        key = _canonical(sig)
        group = qualifying.get(key)
        if group is None or key in matched:
            _fail('proposal entry %s is not an independently derived corpus pattern' % eid)
        identity = [sig['relation'], sig['polarity'], sig['modality'], group['order'],
                    sig['segments'], sig['inflection']]
        identity_bytes = json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')
        if eid != 'v73_' + _sha(identity_bytes)[:16] or e['family'] != 'v73_' + sig['relation']:
            _fail('entry id/family is not the canonical independently derived identity')
        if e['order'] != group['order']:
            _fail('entry order disagrees with derived slot order')
        if set(_id_list(e['source_sentence_ids'], 'entry sentence ids', _ROWS)) != group['rows']:
            _fail('entry source sentences differ from derived grouping')
        uids = set(_id_list(e['source_unit_ids'], 'entry unit ids', _MAX_UNITS))
        if uids != group['units']:
            _fail('entry source units are not grounded')
        matched[key] = eid
    if set(matched) != set(qualifying):
        _fail('proposal entries do not equal the derived patterns')
    derived_mods = {form: (frozenset(v[0]), frozenset(v[1])) for form, v in modifiers.items()}
    if len(derived_mods) > _MAX_MODIFIERS:
        _fail('too many modifiers')
    if (_norm_modifiers(proposal['modifier_terms'], 'proposal modifier') != derived_mods
            or _norm_modifiers(corpus['modifier_terms'], 'corpus modifier') != derived_mods):
        _fail('modifier terms differ from corpus derivation')
    out = []
    for key in sorted(qualifying):
        group = qualifying[key]
        for seg in group['sig']['segments']:
            value = seg.get('literal', seg.get('predicate'))
            if value is None:
                continue
            for core in cores:
                if core in value:
                    _fail('segment holds a concrete role word')
        out.append({'sig': group['sig'], 'order': group['order'], 'digest': _sha(key),
                    'id': matched[key]})
    return out, sorted(derived_mods), sorted(texts)


# --- graph assembly ------------------------------------------------------------------

class _Graph:
    def __init__(self, g):
        self.g = g
        self.nodes = g['공통층']
        self.edges = g['엣지']
        self.count = 0
        self.values = {}
        for name, examples in self.nodes.items():
            if type(examples) is list and len(examples) == 1 and type(examples[0]) is str:
                if examples[0].startswith('s=') or examples[0] in ('b=true', 'b=false'):
                    self.values.setdefault(examples[0], name)
        self.scalar_rewrites = []
        for index, edge in enumerate(self.edges):
            target = edge[2]
            examples = self.nodes.get(target)
            if (type(examples) is list and len(examples) == 1 and type(examples[0]) is str
                    and examples[0] in self.values):
                canonical = self.values[examples[0]]
                if target != canonical:
                    self.edges[index] = [edge[0], edge[1], canonical]
                    self.scalar_rewrites.append((target, canonical))
        self.taken = set()
        for layer in ('공통층', '사례층', '무관층'):
            self.taken.update(g.get(layer) or {})
        if any(name.startswith(_PREFIX) for name in self.taken):
            _fail('base graph already holds V73 names')

    def targets(self, a, rel):
        return [e[2] for e in self.edges if e[0] == a and e[1] == rel]

    def link(self, a, rel):
        found = self.targets(a, rel)
        if len(found) != 1:
            _fail('graph link %s -%s-> is not unique' % (a, rel))
        return found[0]

    def scalar(self, name):
        ex = self.nodes.get(name)
        if type(ex) is not list or len(ex) != 1 or type(ex[0]) is not str:
            _fail('graph node %r is not a scalar' % name)
        value = ex[0]
        if value.startswith('s='):
            return value[2:]
        if value == 'b=true':
            return True
        if value == 'b=false':
            return False
        if value == 'n=null':
            return None
        if value.startswith('i='):
            try:
                return int(value[2:])
            except ValueError:
                pass
        _fail('graph node %r has an unknown scalar' % name)

    def op(self, name):
        return self.scalar(self.link(name, 'op'))

    def sequence(self, name):
        firsts = self.targets(name, 'first')
        if not firsts:
            return []
        if len(firsts) != 1:
            _fail('sequence %r has several heads' % name)
        items = [firsts[0]]
        while True:
            nxt = self.targets(items[-1], 'next')
            if not nxt:
                return items
            if len(nxt) != 1 or nxt[0] in items or len(items) >= 256:
                _fail('sequence %r is malformed' % name)
            items.append(nxt[0])

    def new(self, label):
        name = _PREFIX + label
        if name in self.taken:
            _fail('graph name collision %r' % name)
        self.taken.add(name)
        self.nodes[name] = ['n=null']
        return name

    def value(self, value):
        if type(value) is bool:
            encoded = 'b=true' if value else 'b=false'
        else:
            _safe_scalar(value)
            encoded = 's=' + value
        if encoded in self.values:
            return self.values[encoded]
        self.count += 1
        name = self.new('leaf%d' % self.count)
        self.nodes[name] = [encoded]
        self.values[encoded] = name
        return name

    def edge(self, a, rel, b):
        self.edges.append([a, rel, b])

    def node(self, label, opname):
        name = self.new(label)
        self.edge(name, 'op', self.value(opname))
        return name

    def chain(self, label, items):
        seq = self.node(label, 'sequence')
        prev = None
        for item in items:
            self.edge(seq if prev is None else prev, 'first' if prev is None else 'next', item)
            prev = item
        return seq


def _grammar(graph, root, members):
    ref = graph.link(root, 'grammar-ref')
    if graph.op(ref) != 'grammar-ref':
        _fail('grammar-ref has the wrong op')
    path = graph.scalar(graph.link(ref, 'member-path'))
    sha = graph.scalar(graph.link(ref, 'sha256'))
    data = members.get(path)
    if (type(data) is not bytes or len(data) > _MAX_GRAMMAR_BYTES or type(sha) is not str
            or _sha(data) != sha):
        _fail('grammar member missing or digest mismatch')
    doc = _load_json(data, 'grammar', canonical=False)
    try:
        infl = doc['language_pack']['inflection']
        parsing = infl['parsing_endings']
        kinds = infl['kinds']
        declared = infl['endings']
    except (KeyError, TypeError):
        _fail('grammar lacks inflection declarations')
    if (type(parsing) is not list or type(kinds) is not list or type(declared) is not dict
            or any(type(x) is not str or x not in declared for x in parsing)
            or any(type(x) is not str for x in kinds)):
        _fail('grammar inflection declarations invalid')
    return tuple(parsing), tuple(kinds)


def _head_pattern(mods):
    parts = []
    for index, mod in enumerate(mods):
        guard = ''.join('(?<!%s )' % re.escape(prior) for prior in mods[:index])
        parts.append('(?:%s%s )?' % (guard, re.escape(mod)))
    pattern = ''.join(parts) + _ORIGINAL_HEAD
    if len(pattern) > _HEAD_CAP:
        _fail('head pattern exceeds %d characters' % _HEAD_CAP)
    for ch in _UNSAFE_CHARS:
        if ch in pattern:
            _fail('head pattern is not graph-writable')
    try:
        compiled = re.compile(pattern)
    except re.error:
        _fail('head pattern does not compile')
    if compiled.fullmatch('') or not compiled.fullmatch('가'):
        _fail('head pattern lost its original behaviour')
    for first in mods:
        if not compiled.fullmatch(first + ' 가'):
            _fail('head pattern rejects an approved modifier')
        for second in mods:
            if compiled.fullmatch(first + ' ' + second + ' 가'):
                _fail('head pattern admits stacked modifiers')
    return pattern


def _assemble(graph, root, entries, modifiers, corpus_texts, basis=None):
    if graph.op(root) != 'root':
        _fail('language root is not op=root')
    if graph.targets(root, 'lexical-negations'):
        _fail('base graph already holds a lexical-negation map')
    head_leaf = graph.link(root, 'head-pattern')
    if graph.scalar(head_leaf) != _ORIGINAL_HEAD:
        _fail('base head pattern is not the original pattern')
    items = graph.sequence(graph.link(root, 'rules'))
    if not items:
        _fail('base root has no rules')
    rolemap = {}
    baserules = {}
    lexical = []
    basebinds = {}
    basemeanings = {}
    for item in items:
        rule = graph.link(item, 'target')
        if graph.op(rule) != 'rule':
            _fail('root rule item does not target a rule')
        meaning = graph.link(rule, 'emits')
        sense = graph.link(meaning, 'relation')
        subjects = [graph.link(x, 'target') for x in graph.sequence(graph.link(meaning, 'subjects'))]
        if len(subjects) != 1:
            continue
        pair = (subjects[0], graph.link(meaning, 'object'))
        if rolemap.setdefault(sense, pair) != pair:
            _fail('base rules disagree on roles for %r' % sense)
        basebinds.setdefault(sense, graph.link(rule, 'binds'))
        if sense not in basemeanings:
            baserules[sense] = (rule, items.index(item))
        basemeanings.setdefault(sense, meaning)
    inflections = {}
    ending_sequences = {}
    negative_meanings = {}
    new_values = []
    for index, entry in enumerate(entries):
        sig = entry['sig']
        relation = sig['relation']
        if relation not in rolemap or relation not in graph.nodes or graph.op(relation) != 'sense':
            _fail('relation %r has no existing common sense and roles' % relation)
        roles = {'subject': rolemap[relation][0], 'object': rolemap[relation][1]}
        info = {}
        for key, role in roles.items():
            if graph.op(role) != 'role' or graph.scalar(graph.link(role, 'mode')) != 'suffix':
                _fail('existing role is not a suffix role')
            seed = graph.scalar(graph.link(role, 'seed'))
            markers = [graph.scalar(graph.link(x, 'value'))
                       for x in graph.sequence(graph.link(role, 'markers'))]
            if type(seed) is not str or not seed or not markers:
                _fail('existing role lacks seed or markers')
            info[key] = (seed, markers)
        segs = sig['segments']
        for j, seg in enumerate(segs):
            if 'slot' in seg:
                nxt = segs[j + 1] if j + 1 < len(segs) else None
                if (nxt is None or 'literal' not in nxt
                        or not any(nxt['literal'].startswith(m) for m in info[seg['slot']][1])):
                    _fail('slot is not followed by a known role marker')
        rendered = ''.join(info[s['slot']][0] if 'slot' in s else s.get('literal', s.get('predicate'))
                           for s in segs)
        for key in roles:
            if rendered.count(info[key][0]) != 1:
                _fail('role seed is not unique in rendered reads')
        tag = 'e%02d_%s' % (index, entry['digest'][:12])
        rule = graph.node(tag, 'rule')
        graph.edge(rule, 'binds', basebinds[relation])
        reads = []
        for j, seg in enumerate(segs):
            if 'slot' in seg:
                item = graph.node('%s_read%d' % (tag, j), 'slot')
                graph.edge(item, 'role', roles[seg['slot']])
            else:
                kind = 'literal' if 'literal' in seg else 'predicate'
                item = graph.node('%s_read%d' % (tag, j), kind)
                graph.edge(item, 'value', graph.value(seg[kind]))
                new_values.append(seg[kind])
            reads.append(item)
        reads_seq = graph.chain(tag + '_reads', reads)
        graph.edge(rule, 'reads', reads_seq)
        if sig['polarity'] is True:
            meaning = basemeanings[relation]
        else:
            meaning = negative_meanings.get(relation)
            if meaning is None:
                meaning = graph.node(tag + '_meaning', 'meaning')
                graph.edge(meaning, 'subjects', graph.link(basemeanings[relation], 'subjects'))
                graph.edge(meaning, 'relation', relation)
                graph.edge(meaning, 'object', roles['object'])
                graph.edge(meaning, 'polarity', graph.value(False))
                negative_meanings[relation] = meaning
        graph.edge(rule, 'emits', meaning)
        if sig['polarity'] is False:
            lexical.append((relation, rule))
        infl = sig['inflection']
        ending_key = tuple(infl['endings']) if infl is not None else ()
        endings = ending_sequences.get(ending_key)
        if endings is None:
            ending_items = []
            for k, name in enumerate(ending_key):
                item = graph.node('%s_ending%d' % (tag, k), 'scalar')
                graph.edge(item, 'value', graph.value(name))
                ending_items.append(item)
            endings = graph.chain(tag + '_endings', ending_items)
            ending_sequences[ending_key] = endings
        if infl is not None:
            ikey = (infl['stem'], infl['kind'], infl['canonical_ending'], ending_key)
            ref = inflections.get(ikey)
            if ref is None:
                ref = graph.node(tag + '_inflection', 'inflection-ref')
                graph.edge(ref, 'stem', graph.value(infl['stem']))
                graph.edge(ref, 'tense', graph.value('present'))
                graph.edge(ref, 'ending', graph.value(infl['canonical_ending']))
                graph.edge(ref, 'kind', graph.value(infl['kind']))
                graph.edge(ref, 'endings', endings)
                inflections[ikey] = ref
            graph.edge(rule, 'inflection-ref', ref)
        graph.edge(rule, 'allowed-endings', endings)
        graph.edge(rule, 'realizes', reads_seq)
        item = graph.node(tag + '_rule_ref', 'rule-ref')
        graph.edge(item, 'target', rule)
        graph.edge(items[-1], 'next', item)
        items.append(item)
    if modifiers:
        pattern = _head_pattern(list(modifiers))
        where = [k for k, e in enumerate(graph.edges) if e[0] == root and e[1] == 'head-pattern']
        if len(where) != 1:
            _fail('head-pattern edge is not unique')
        graph.edges[where[0]] = [root, 'head-pattern', graph.value(pattern)]
        new_values.append(pattern)
    for value in new_values:
        for text in corpus_texts:
            if text in value:
                _fail('deployed graph would hold a raw training sentence')
    if lexical:
        if (type(basis) is not list or len(basis) != 2
                or any(type(i) is not int for i in basis) or basis != [0, 1]):
            _fail('base grammar lacks the exact negative basis [0, 1]')
        if len(lexical) > 2 or len({rule for _relation, rule in lexical}) != len(lexical):
            _fail('lexical map needs at most two unique negative rules')
        refs = []
        for k, (relation, neg_rule) in enumerate(lexical):
            pos_rule, pos_index = baserules[relation]
            if pos_index not in basis:
                _fail('positive base rule is outside the negative basis')
            pos_meaning = graph.link(pos_rule, 'emits')
            neg_meaning = graph.link(neg_rule, 'emits')
            pos_polarity = graph.targets(pos_meaning, 'polarity')
            neg_polarity = graph.targets(neg_meaning, 'polarity')
            if pos_polarity and not (len(pos_polarity) == 1 and graph.scalar(pos_polarity[0]) is True):
                _fail('positive base rule is not positive')
            if (len(neg_polarity) != 1 or graph.scalar(neg_polarity[0]) is not False
                    or graph.link(pos_rule, 'binds') != graph.link(neg_rule, 'binds')
                    or graph.link(pos_meaning, 'relation') != relation
                    or graph.link(neg_meaning, 'relation') != relation
                    or graph.link(pos_meaning, 'subjects') != graph.link(neg_meaning, 'subjects')
                    or graph.link(pos_meaning, 'object') != graph.link(neg_meaning, 'object')):
                _fail('negative and positive rules do not share relation and roles')
            ref = graph.node('lex%d_ref' % k, 'lexical-negation-ref')
            graph.edge(ref, 'negative-rule', neg_rule)
            graph.edge(ref, 'positive-rule', pos_rule)
            refs.append(ref)
        sequence = graph.chain('lex_sequence', refs)
        graph.edge(root, 'lexical-negations', sequence)


def _negative_basis(graph, root, members):
    ref = graph.link(root, 'grammar-ref')
    data = members.get(graph.scalar(graph.link(ref, 'member-path')))
    if type(data) is not bytes:
        return None
    doc = _load_json(data, 'grammar', canonical=False)
    try:
        basis = doc['semantic_capabilities']['negative_binary']['frame_indices']
    except (KeyError, TypeError):
        return None
    return list(basis) if (type(basis) is list and len(basis) == 2
                           and all(type(i) is int for i in basis) and basis == [0, 1]) else None


def _projection_budget(graph, root):
    # Conservative source-shape walk for dialogue projection. The root op consumes
    # the action-grounding target, but its separate action projector owns descendants.
    outgoing = {}
    for a, relation, target in graph.edges:
        outgoing.setdefault(a, []).append((relation, target))
    nodes, edges = set(), set()
    pending = [root]
    while pending:
        name = pending.pop()
        if name in nodes:
            continue
        nodes.add(name)
        for relation, target in outgoing.get(name, ()):
            edges.add((name, relation, target))
            if name == root and relation == 'action-grounding':
                nodes.add(target)
            else:
                pending.append(target)
    if len(nodes) > 512 or len(edges) > 1024:
        _fail('derived language graph exceeds existing projection node/edge budgets')
    return len(nodes), len(edges)


# --- builder -------------------------------------------------------------------------

def build_foundation_language_pack(base_pack, corpus_path, proposal_path, output, *, expected_base_sha256):
    '''Build a new V73 pack from base_pack plus the verified corpus/proposal; return a receipt.'''
    if type(expected_base_sha256) is not str or not _SHA_RE.fullmatch(expected_base_sha256):
        _fail('expected_base_sha256 must be 64 lowercase hex')
    src = _path(base_pack, 'base pack')
    cpath = _path(corpus_path, 'corpus')
    ppath = _path(proposal_path, 'proposal')
    dst = _path(output, 'output')
    if len({src, cpath, ppath, dst}) != 4:
        _fail('input and output paths must be distinct')
    parent = os.path.dirname(dst)
    if os.path.lexists(dst) or not os.path.isdir(parent):
        _fail('output must be a new path in an existing directory')
    reals = [os.path.realpath(p) for p in (src, cpath, ppath)]
    if len(set(reals)) != 3 or os.path.realpath(dst) in reals:
        _fail('invalid input/output relation')
    if _sha(_read_bounded(src, _MAX_PACK_BYTES, 'base pack')) != expected_base_sha256:
        _fail('base pack sha256 mismatch')
    corpus_bytes = _read_bounded(cpath, _MAX_JSON_BYTES, 'corpus')
    proposal_bytes = _read_bounded(ppath, _MAX_JSON_BYTES, 'proposal')
    corpus = _load_json(corpus_bytes, 'corpus', canonical=True)
    proposal = _load_json(proposal_bytes, 'proposal', canonical=True)
    corpus_sha = _sha(corpus_bytes)
    proposal_sha = _sha(proposal_bytes)
    if type(proposal) is not dict or proposal.get('corpus_sha256') != corpus_sha:
        _fail('proposal is not bound to the exact corpus bytes')

    from marco.storage import graph_text, kgpack

    try:
        manifest, members = kgpack.read(src)
    except kgpack.KGPackError as exc:
        raise FoundationBuildError('base pack unreadable: %s' % exc) from exc
    if _sha(_read_bounded(src, _MAX_PACK_BYTES, 'base pack')) != expected_base_sha256:
        _fail('base pack changed while reading')
    model = manifest.get('model')
    language = model.get('language_graph') if isinstance(model, dict) else None
    if not isinstance(language, dict):
        _fail('base pack declares no language graph')
    member, root = language.get('member_path'), language.get('root')
    if member != _GRAPH_MEMBER or type(root) is not str or member not in members:
        _fail('base language graph is not the expected member')
    graph_bytes = members[member]
    try:
        g = graph_text.parse(graph_bytes, member)
    except graph_text.GraphTextError as exc:
        raise FoundationBuildError('base graph unreadable: %s' % exc) from exc
    old_nodes = copy.deepcopy(g['공통층'])
    old_edges = copy.deepcopy(g['엣지'])
    graph = _Graph(g)
    parsing_endings, kinds = _grammar(graph, root, members)
    entries, modifiers, texts = _derive(corpus, proposal, expected_base_sha256, parsing_endings, kinds)
    basis = _negative_basis(graph, root, members)
    _assemble(graph, root, entries, modifiers, texts, basis)
    _projection_budget(graph, root)
    try:
        new_graph = graph_text.write(g, member).encode('utf-8')
        check = graph_text.parse(new_graph, member)
    except graph_text.GraphTextError as exc:
        raise FoundationBuildError('assembled graph is not writable: %s' % exc) from exc
    if check['공통층'] != g['공통층'] or check['엣지'] != g['엣지']:
        _fail('assembled graph does not read back equal')
    for name, examples in old_nodes.items():
        if check['공통층'].get(name) != examples:
            _fail('original graph node changed')
    changed = [(a, b) for a, b in zip(old_edges, check['엣지']) if a != b]
    if len(check['엣지']) < len(old_edges):
        _fail('original graph edges were removed')
    for before, after in changed:
        if before[:2] != after[:2]:
            _fail('original structural edge changed')
        if before[0] == root and before[1] == 'head-pattern':
            continue
        old_value = old_nodes.get(before[2])
        new_value = old_nodes.get(after[2])
        if (type(old_value) is not list or len(old_value) != 1 or old_value != new_value
                or type(old_value[0]) is not str
                or not (old_value[0].startswith('s=') or old_value[0] in ('b=true', 'b=false'))):
            _fail('original edge changed beyond identical typed scalar canonicalization')

    manifest2 = copy.deepcopy(manifest)
    hits = [x for x in manifest2.get('files', []) if isinstance(x, dict) and x.get('path') == member]
    if len(hits) != 1:
        _fail('manifest graph entry is not unique')
    entry = hits[0]
    entry['bytes'] = len(new_graph)
    entry['sha256'] = _sha(new_graph)
    if 'lf_normalized_sha256' in entry or 'line_endings' in entry:
        ident = kgpack.content_identity(new_graph)
        for key in ('lf_normalized_sha256', 'line_endings'):
            if key in entry:
                entry[key] = ident[key]
    members2 = dict(members)
    members2[member] = new_graph
    mbytes = (json.dumps(manifest2, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
              + _LF).encode('utf-8')
    for value, label in ((src, 'base pack'), (cpath, 'corpus'), (ppath, 'proposal'), (dst, 'output')):
        _path(value, label)
    fd, tmp = tempfile.mkstemp(prefix='.v73-foundation-', suffix='.tmp', dir=parent)
    try:
        with os.fdopen(fd, 'wb') as fh:
            with zipfile.ZipFile(fh, 'w') as zf:
                kgpack._write(zf, 'manifest.json', mbytes)
                for name in sorted(members2):
                    kgpack._write(zf, name, members2[name])
            fh.flush()
            os.fsync(fh.fileno())
        try:
            m2, d2 = kgpack.read(tmp)
        except kgpack.KGPackError as exc:
            raise FoundationBuildError('built pack does not verify: %s' % exc) from exc
        if m2 != manifest2 or d2 != members2:
            _fail('built pack does not match the expected content')
        for name, body in members.items():
            if name != member and d2.get(name) != body:
                _fail('preserved member changed: %s' % name)
        with open(tmp, 'rb') as fh:
            out = fh.read()
        for value, label in ((src, 'base pack'), (cpath, 'corpus'), (ppath, 'proposal'), (dst, 'output')):
            _path(value, label)
        if (_sha(_read_bounded(src, _MAX_PACK_BYTES, 'base pack')) != expected_base_sha256
                or _sha(_read_bounded(cpath, _MAX_JSON_BYTES, 'corpus')) != corpus_sha
                or _sha(_read_bounded(ppath, _MAX_JSON_BYTES, 'proposal')) != proposal_sha):
            _fail('input bytes changed before publication')
        if os.path.lexists(dst):
            _fail('output already exists')
        try:
            os.link(tmp, dst)
        except FileExistsError:
            _fail('output already exists')
        except OSError as exc:
            raise FoundationBuildError('exclusive publication failed: %s' % exc) from exc
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return {'output_path': dst, 'sha256': _sha(out), 'bytes': len(out), 'corpus_sha256': corpus_sha,
            'proposal_sha256': proposal_sha, 'entry_count': len(entries),
            'modifier_count': len(modifiers), 'scope': _SCOPE}
