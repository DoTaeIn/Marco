'''Offline corpus-first supervised language knowledge preparation, no runtime engine.

Stdlib only. Human semantic supervision is explicit (teacher-supervised public
training data); nothing here discovers meaning without supervision.
'''
import hashlib
import json
import os
import re

CORPUS_SCHEMA = 'marco-foundation-language-corpus-v1'
PROPOSAL_SCHEMA = 'marco-foundation-language-proposal-v1'
INVENTORY_SCHEMA = 'marco-foundation-language-inventory-v1'
RECEIPT_SCHEMA = 'marco-foundation-corpus-receipt-v1'
MAX_BYTES = 1048576
MAX_ENTRIES = 12
MAX_MODIFIERS = 8
MAX_ROWS = 300
MAX_TEXT = 256
MAX_UNIT_IDS = 16
MAX_LITERAL = 64
MAX_HEAD = 128
MAX_UNITS = 256
MIN_PAIRS = 3
_SHA = re.compile(r'[0-9a-f]{64}')
_ENDINGS = ('plain', 'informal', 'polite', 'formal')
_KINDS = ('lexical', 'inflection', 'particle', 'nounphrase_modifier', 'word_order')
_MODS = ('파란', '빨간', '노란', '하얀')
_ENDING_FORMS = {'plain': '다', 'polite': '어요', 'formal': '습니다'}

_POOLS = {
    'pv': ('민수', '지아', '서하', '도하', '나리', '하나', '유리', '소라', '세아', '로하'),
    'pb': ('철민', '영진', '정훈', '승현', '재민', '동건', '준혁', '성진', '민준', '현빈'),
    'tv': ('사과', '모자', '지도', '구두', '카메라', '노트', '우비', '부채', '의자', '도마'),
    'tb': ('책', '지갑', '우산', '안경', '공책', '연필', '신발', '장갑', '거울', '달력'),
    'pl': ('도서관', '학교', '공원', '정류장', '부엌', '마당', '서재', '창고', '교실', '사무실'),
}

# relation, polarity, subject particle kind, subject pool, object pool,
# object particle kind, order, predicate, inflection ending, inflection stem
_FAMILIES = (
    ('seed_owns', True, 'top', 'pv', 'tb', 'obj', 'SO', '가지고 있다', 'plain', '있'),
    ('seed_owns', True, 'nom', 'pb', 'tv', 'obj', 'SO', '가지고 있다', 'plain', '있'),
    ('seed_owns', True, 'top', 'pb', 'tv', 'obj', 'SO', '소유한다', None, None),
    ('seed_owns', True, 'nom', 'pv', 'tb', 'obj', 'SO', '보유한다', None, None),
    ('seed_located_in', True, 'top', 'tv', 'pl', '에', 'SO', '있다', 'plain', '있'),
    ('seed_located_in', True, 'nom', 'tb', 'pl', '에', 'SO', '있다', 'plain', '있'),
    ('seed_located_in', True, 'top', 'tb', 'pl', '에는', 'SO', '있다', 'plain', '있'),
    ('seed_located_in', True, 'top', 'tv', 'pl', '에', 'SO', '위치한다', None, None),
    ('seed_located_in', False, 'top', 'tv', 'pl', '에', 'SO', '없다', 'plain', '없'),
    ('seed_located_in', False, 'top', 'tb', 'pl', '에는', 'SO', '없다', 'plain', '없'),
    ('seed_owns', True, 'top', 'pv', 'tb', 'obj', 'OS', '가지고 있다', 'plain', '있'),
    ('seed_located_in', True, 'nom', 'tv', 'pl', '에', 'OS', '있다', 'plain', '있'),
)


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def canonical_bytes(value):
    return _dumps(value).encode('utf-8') + bytes([10])


def _sha_of(data):
    return hashlib.sha256(data).hexdigest()


def _check_sha(value):
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError('sha256 must be 64 lowercase hex characters')
    return value


def _batchim(word):
    code = ord(word[-1]) - 0xAC00
    return 0 <= code < 11172 and code % 28 != 0


def _subject_particle(kind, word):
    b = _batchim(word)
    if kind == 'top':
        return '은' if b else '는'
    return '이' if b else '가'


def _plain(value, depth=0):
    if depth > 6:
        raise ValueError('metadata too deep')
    kind = type(value)
    if value is None or kind is bool or kind is int:
        return
    if kind is str:
        if len(value) > MAX_TEXT:
            raise ValueError('metadata string too long')
        return
    if kind is list:
        if len(value) > 32:
            raise ValueError('metadata list too long')
        for item in value:
            _plain(item, depth + 1)
        return
    if kind is dict:
        if len(value) > 32:
            raise ValueError('metadata dict too large')
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError('metadata key must be str')
            _plain(item, depth + 1)
        return
    raise ValueError('metadata value is not plain')


def _check_inflection(infl, form):
    if infl is None:
        return None
    if type(infl) is not dict or set(infl) != {'stem', 'kind', 'endings', 'canonical_ending'}:
        raise ValueError('inflection must be null or exact stem/kind/endings/canonical_ending')
    if type(infl['stem']) is not str or infl['stem'] not in ('있', '없'):
        raise ValueError('inflection stem must be 있 or 없')
    if type(infl['kind']) is not str or infl['kind'] != 'existential':
        raise ValueError('inflection kind must be existential')
    ends = infl['endings']
    if (type(ends) is not list or not ends or len(set(ends)) != len(ends)
            or any(type(e) is not str or e not in _ENDINGS for e in ends)):
        raise ValueError('inflection endings invalid')
    if type(infl['canonical_ending']) is not str or infl['canonical_ending'] != 'plain' or 'plain' not in ends:
        raise ValueError('canonical ending must be plain')
    if not form.endswith(infl['stem'] + '다'):
        raise ValueError('predicate form must end in the canonical plain stem form')
    return infl


def _modifier_terms(units, sentences):
    terms = []
    for unit in sorted(units.values(), key=lambda u: u['id']):
        if unit['kind'] != 'nounphrase_modifier':
            continue
        form = unit['form']
        ok = []
        for sid in unit['source_sentence_ids']:
            sent = sentences[sid]
            for role in ('subject', 'object'):
                a, b = sent['slot_spans'][role]
                ent = sent['text'][a:b]
                if ent.startswith(form + ' ') and len(ent) > len(form) + 1:
                    ok.append(sid)
                    break
        if ok:
            terms.append({'text': form, 'source_sentence_ids': sorted(ok), 'source_unit_ids': [unit['id']]})
    if len(terms) > MAX_MODIFIERS:
        raise ValueError('too many modifier terms')
    return terms


def generate_corpus(source_pack_sha256):
    _check_sha(source_pack_sha256)
    registry = {}

    def unit(kind, form, meta):
        key = (kind, form, _dumps(meta))
        if key not in registry:
            registry[key] = {'id': 'unit_%03d' % (len(registry) + 1), 'kind': kind, 'form': form,
                             'meaning_metadata': meta, 'source_sentence_ids': []}
        return registry[key]

    sentences = []
    for f, fam in enumerate(_FAMILIES):
        rel, pol, skind, spool, opool, okind, order, pred, ending, stem = fam
        infl = None
        if ending is not None:
            infl = {'stem': stem, 'kind': 'existential', 'endings': list(_ENDINGS),
                    'canonical_ending': 'plain'}
        for i in range(25):
            subj = _POOLS[spool][((i % 10) + f) % 10]
            obj = _POOLS[opool][(3 * i + i // 10 + f) % 10]
            mod = None
            if i % 5 == 0:
                mod = _MODS[(i // 5 + f) % 4]
                if rel == 'seed_owns':
                    obj = mod + ' ' + obj
                else:
                    subj = mod + ' ' + subj
            sp = _subject_particle(skind, subj)
            if okind == 'obj':
                op = '을' if _batchim(obj) else '를'
            else:
                op = okind
            if order == 'SO':
                s0 = 0
                s1 = len(subj)
                t = subj + sp + ' '
                o0 = len(t)
                o1 = o0 + len(obj)
                t += obj + op + ' '
            else:
                o0 = 0
                o1 = len(obj)
                t = obj + op + ' '
                s0 = len(t)
                s1 = s0 + len(subj)
                t += subj + sp + ' '
            p0 = len(t)
            text = t + pred
            lex_meta = {'relation': rel, 'polarity': pol, 'modality': 'asserted', 'inflection': infl}
            used = [unit('lexical', pred, lex_meta),
                    unit('particle', sp, {'role': 'subject'}),
                    unit('particle', op, {'role': 'object_owns' if rel == 'seed_owns' else 'object_located'}),
                    unit('word_order', 'subject_object' if order == 'SO' else 'object_subject',
                         {'order': 'subject_object' if order == 'SO' else 'object_subject'})]
            if ending is not None:
                used.append(unit('inflection', _ENDING_FORMS[ending], {'ending': ending}))
            if mod is not None:
                used.append(unit('nounphrase_modifier', mod, {'category': 'color_adjective'}))
            sid = 's%03d' % (f * 25 + i + 1)
            for u in used:
                u['source_sentence_ids'].append(sid)
            sentences.append({
                'id': sid, 'text': text, 'entry_id': 'seed_f%02d' % (f + 1),
                'slots': {'subject': subj, 'object': obj},
                'slot_spans': {'subject': [s0, s1], 'object': [o0, o1]},
                'predicate_span': [p0, len(text)],
                'meaning': {'triple': [subj, rel, obj], 'polarity': pol, 'modality': 'asserted'},
                'unit_ids': [u['id'] for u in used]})
    units = sorted(registry.values(), key=lambda u: u['id'])
    for u in units:
        u['source_sentence_ids'] = sorted(set(u['source_sentence_ids']))
    by_sid = {s['id']: s for s in sentences}
    return {'schema': CORPUS_SCHEMA, 'source_pack_sha256': source_pack_sha256,
            'sentences': sentences, 'units': units,
            'modifier_terms': _modifier_terms({u['id']: u for u in units}, by_sid)}


def _span(value, length):
    if type(value) is not list or len(value) != 2 or any(type(v) is not int for v in value):
        raise ValueError('span must be [int,int]')
    a, b = value
    if not 0 <= a < b <= length:
        raise ValueError('span out of bounds')
    return a, b


def _str_list(value, cap):
    if type(value) is not list or len(value) > cap or len(set(value)) != len(value):
        raise ValueError('expected unique string list')
    for v in value:
        if type(v) is not str or not v:
            raise ValueError('expected nonempty strings')
    return value


def _validate_corpus(corpus):
    if type(corpus) is not dict:
        raise ValueError('corpus must be a dict')
    required = {'schema', 'source_pack_sha256', 'sentences', 'units'}
    keys = set(corpus)
    if not required <= keys or keys - required - {'candidate_entries', 'modifier_terms'}:
        raise ValueError('corpus key set invalid')
    try:
        size = len(canonical_bytes(corpus))
    except (TypeError, ValueError):
        raise ValueError('corpus is not plain JSON') from None
    if size > MAX_BYTES:
        raise ValueError('corpus exceeds byte bound')
    if type(corpus['schema']) is not str or corpus['schema'] != CORPUS_SCHEMA:
        raise ValueError('corpus schema mismatch')
    _check_sha(corpus['source_pack_sha256'])
    raw_units, raw_sents = corpus['units'], corpus['sentences']
    if type(raw_units) is not list or len(raw_units) > MAX_UNITS:
        raise ValueError('units invalid')
    if type(raw_sents) is not list or len(raw_sents) != MAX_ROWS:
        raise ValueError('sentences invalid')
    units = {}
    for u in raw_units:
        if type(u) is not dict or set(u) != {'id', 'kind', 'form', 'meaning_metadata', 'source_sentence_ids'}:
            raise ValueError('unit key set invalid')
        if type(u['id']) is not str or not u['id'] or len(u['id']) > 64 or u['id'] in units:
            raise ValueError('unit id invalid')
        if type(u['kind']) is not str or u['kind'] not in _KINDS:
            raise ValueError('unit kind invalid')
        if type(u['form']) is not str or not u['form'] or len(u['form']) > 64:
            raise ValueError('unit form invalid')
        if type(u['meaning_metadata']) is not dict:
            raise ValueError('unit metadata must be dict')
        _plain(u['meaning_metadata'])
        _str_list(u['source_sentence_ids'], MAX_ROWS)
        units[u['id']] = u
    sents = {}
    texts = set()
    for s in raw_sents:
        want = {'id', 'text', 'entry_id', 'slots', 'slot_spans', 'predicate_span', 'meaning', 'unit_ids'}
        if type(s) is not dict or set(s) != want:
            raise ValueError('sentence key set invalid')
        if type(s['id']) is not str or not s['id'] or s['id'] in sents:
            raise ValueError('sentence id invalid')
        text = s['text']
        if type(text) is not str or not 1 <= len(text) <= MAX_TEXT or text != text.strip() or text in texts:
            raise ValueError('sentence text invalid')
        if text[-1] in '.?!。':
            raise ValueError('trailing punctuation not allowed')
        texts.add(text)
        if type(s['entry_id']) is not str or len(s['entry_id']) > 64:
            raise ValueError('entry_id invalid')
        slots, spans = s['slots'], s['slot_spans']
        if (type(slots) is not dict or set(slots) != {'subject', 'object'}
                or type(spans) is not dict or set(spans) != {'subject', 'object'}):
            raise ValueError('slots invalid')
        parts = []
        for role in ('subject', 'object'):
            a, b = _span(spans[role], len(text))
            if type(slots[role]) is not str or text[a:b] != slots[role]:
                raise ValueError('slot text does not match span')
            parts.append((a, b))
        parts.append(_span(s['predicate_span'], len(text)))
        parts.sort()
        for left, right in zip(parts, parts[1:]):
            if left[1] > right[0]:
                raise ValueError('spans overlap')
        m = s['meaning']
        if type(m) is not dict or set(m) != {'triple', 'polarity', 'modality'}:
            raise ValueError('meaning invalid')
        t = m['triple']
        if type(t) is not list or len(t) != 3 or any(type(x) is not str for x in t):
            raise ValueError('triple invalid')
        if t[0] != slots['subject'] or t[2] != slots['object']:
            raise ValueError('triple does not match slots')
        if type(m['polarity']) is not bool or type(m['modality']) is not str or m['modality'] != 'asserted':
            raise ValueError('polarity/modality invalid')
        ids = _str_list(s['unit_ids'], MAX_UNIT_IDS)
        for uid in ids:
            if uid not in units:
                raise ValueError('unknown unit id')
        sents[s['id']] = s
    for u in units.values():
        members = {sid for sid, s in sents.items() if u['id'] in s['unit_ids']}
        if set(u['source_sentence_ids']) != members:
            raise ValueError('unit source membership is not the inverse of sentence unit_ids')
        if u['kind'] != 'word_order':
            for sid in members:
                if u['form'] not in sents[sid]['text']:
                    raise ValueError('unit form does not occur in its source sentence')
    return raw_sents, units, sents


def _validate_base(base):
    if type(base) is not dict:
        raise ValueError('base declarations must be a dict')
    for k in ('relations', 'roles', 'predicates', 'head_pattern'):
        if k not in base:
            raise ValueError('base declarations lack ' + k)
    rels = _str_list(base['relations'], 16)
    roles = base['roles']
    if type(roles) is not dict:
        raise ValueError('roles invalid')
    for k in ('subject', 'object_owns', 'object_located'):
        _str_list(roles.get(k), 16)
    preds = _str_list(base['predicates'], 64)
    head = base['head_pattern']
    if type(head) is not str or not head or len(head) > MAX_HEAD:
        raise ValueError('head pattern invalid')
    re.compile(head)
    return {'relations': set(rels), 'subject': set(roles['subject']),
            'objects': {'seed_owns': set(roles['object_owns']), 'seed_located_in': set(roles['object_located'])},
            'predicates': set(preds), 'head': head}


def _derive(sent, units, base):
    text = sent['text']
    triple = sent['meaning']['triple']
    if triple[1] not in base['relations']:
        return None
    sp = {'subject': tuple(sent['slot_spans']['subject']), 'object': tuple(sent['slot_spans']['object']),
          'predicate': tuple(sent['predicate_span'])}
    lex = [units[u] for u in sent['unit_ids'] if units[u]['kind'] == 'lexical']
    if len(lex) != 1:
        raise ValueError('sentence %s needs exactly one lexical unit' % sent['id'])
    form = lex[0]['form']
    p0, p1 = sp['predicate']
    if p1 != len(text):
        raise ValueError('predicate span must end at the text boundary')
    if text[p0:p1] != form:
        raise ValueError('predicate span must equal the lexical unit form')
    cur = 0
    intervals = []
    for a, b in sorted([sp['subject'], sp['object']]):
        intervals.append((cur, a))
        cur = b
    intervals.append((cur, len(text)))
    hits = []
    for a, b in intervals:
        at = text.find(form, a, b)
        while at >= 0:
            hits.append(at)
            at = text.find(form, at + 1, b)
    if hits != [p0]:
        raise ValueError('predicate form must occur exactly once in remaining intervals')
    meta = lex[0]['meaning_metadata']
    m = sent['meaning']
    if (set(meta) != {'relation', 'polarity', 'modality', 'inflection'} or meta['relation'] != triple[1]
            or type(meta['polarity']) is not bool or meta['polarity'] != m['polarity']
            or meta['modality'] != m['modality']):
        raise ValueError('lexical metadata does not match the sentence meaning')
    infl = _check_inflection(meta['inflection'], form)
    slots = sent['slots']
    items = sorted([('subject', sp['subject']), ('object', sp['object']), ('predicate', sp['predicate'])],
                   key=lambda x: x[1])
    segments = []
    cursor = 0
    for name, (a, b) in items:
        if a > cursor:
            segments.append(_literal(text[cursor:a], slots))
        segments.append({'predicate': form} if name == 'predicate' else {'slot': name})
        cursor = b
    if cursor < len(text):
        segments.append(_literal(text[cursor:], slots))
    order = [n for n, _ in items if n != 'predicate']
    return {'id': sent['id'], 'pair': (slots['subject'], slots['object']), 'relation': triple[1],
            'polarity': m['polarity'], 'modality': m['modality'], 'order': order,
            'segments': segments, 'inflection': infl, 'unit_ids': list(sent['unit_ids'])}


def _literal(value, slots):
    if not value or len(value) > MAX_LITERAL or any(e in value for e in slots.values()):
        raise ValueError('literal segment invalid')
    return {'literal': value}


def analyze_corpus(corpus, base_declarations):
    base = _validate_base(base_declarations)
    raw_sents, units, sents = _validate_corpus(corpus)
    corpus_sha = _sha_of(canonical_bytes(corpus))
    mods = _modifier_terms(units, sents)
    head = base['head']
    if mods:
        head = '(?:(?:%s) )?%s' % ('|'.join(re.escape(t['text']) for t in mods), head)
    if len(head) > MAX_HEAD:
        raise ValueError('combined head pattern exceeds cap')
    regex = re.compile(head)
    groups = {}
    ungrounded = []
    for sent in raw_sents:
        row = _derive(sent, units, base)
        if row is None or not all(regex.fullmatch(e) for e in row['pair']):
            ungrounded.append(sent['id'])
            continue
        key = _dumps([row['relation'], row['polarity'], row['modality'], row['order'],
                      row['segments'], row['inflection']])
        groups.setdefault(key, []).append(row)
    entries = []
    for key in sorted(groups):
        rows = groups[key]
        if len({r['pair'] for r in rows}) < MIN_PAIRS:
            continue
        first = rows[0]
        entries.append({
            'id': 'v73_' + _sha_of(key.encode('utf-8'))[:16],
            'family': 'v73_' + first['relation'],
            'source_sentence_ids': sorted(r['id'] for r in rows),
            'source_unit_ids': sorted({u for r in rows for u in r['unit_ids']}),
            'relation': first['relation'], 'polarity': first['polarity'],
            'modality': first['modality'], 'order': list(first['order']),
            'segments': json.loads(json.dumps(first['segments'])),
            'inflection': json.loads(json.dumps(first['inflection']))})
    if len(entries) > MAX_ENTRIES:
        raise ValueError('too many entries')
    proposal = {'schema': PROPOSAL_SCHEMA, 'corpus_sha256': corpus_sha,
                'source_pack_sha256': corpus['source_pack_sha256'], 'entries': entries,
                'modifier_terms': mods}
    markers = set(base['subject'])
    for v in base['objects'].values():
        markers |= v
    mod_forms = {t['text'] for t in mods}
    inv_units = {k: [] for k in _KINDS}
    for u in sorted(units.values(), key=lambda x: x['id']):
        kind = u['kind']
        if kind == 'lexical':
            meta = u['meaning_metadata']
            status = 'covered_by_base_predicate' if u['form'] in base['predicates'] else 'declared_inventory_gap'
            relation_ok = meta.get('relation') in base['relations']
        elif kind == 'particle':
            status = 'covered_by_base_role_markers' if u['form'] in markers else 'declared_inventory_gap'
            relation_ok = None
        elif kind == 'nounphrase_modifier':
            status = 'approved_for_proposal' if u['form'] in mod_forms else 'declared_inventory_gap'
            relation_ok = None
        else:
            status = 'metadata_only'
            relation_ok = None
        rec = {'id': u['id'], 'form': u['form'], 'meaning_metadata': u['meaning_metadata'],
               'source_sentence_count': len(u['source_sentence_ids']), 'base_status': status}
        if relation_ok is not None:
            rec['known_relation_meaning'] = relation_ok
        inv_units[kind].append(rec)
    inventory = {
        'schema': INVENTORY_SCHEMA,
        'scope': 'supervised corpus-backed inventory; unknown means declared surface inventory gap, not measured native parse failure; predicate meaning is teacher-supervised',
        'corpus_sha256': corpus_sha, 'source_pack_sha256': corpus['source_pack_sha256'],
        'sentence_count': len(raw_sents), 'units': inv_units,
        'ungrounded_sentence_ids': sorted(ungrounded),
        'entries': [{'id': e['id'], 'sentence_count': len(e['source_sentence_ids'])} for e in entries]}
    return {'inventory': inventory, 'proposal': proposal}


def _safe_directory(path):
    if type(path) is not str or not path or chr(0) in path:
        raise ValueError('unsafe output path')
    absolute = os.path.abspath(path)

    def check():
        cur = absolute
        while True:
            if os.path.islink(cur):
                raise ValueError('symlink in output path')
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    check()
    os.makedirs(absolute, exist_ok=True)
    check()
    if not os.path.isdir(absolute):
        raise ValueError('output path is not a directory')
    return absolute


def write_outputs(output_directory, source_pack_sha256, base_declarations):
    corpus = generate_corpus(source_pack_sha256)
    result = analyze_corpus(corpus, base_declarations)
    blobs = {'corpus.json': canonical_bytes(corpus), 'inventory.json': canonical_bytes(result['inventory']),
             'proposal.json': canonical_bytes(result['proposal'])}
    for data in blobs.values():
        if len(data) > MAX_BYTES:
            raise ValueError('output exceeds byte bound')
    directory = _safe_directory(output_directory)
    paths = {name: os.path.join(directory, name) for name in blobs}
    for p in paths.values():
        if os.path.lexists(p):
            raise FileExistsError('refusing to overwrite ' + p)
    files = {}
    for name in sorted(blobs):
        with open(paths[name], 'xb') as handle:
            handle.write(blobs[name])
        files[name] = {'path': paths[name], 'sha256': _sha_of(blobs[name]), 'bytes': len(blobs[name])}
    return {'schema': RECEIPT_SCHEMA, 'files': files,
            'corpus_sha256': files['corpus.json']['sha256'],
            'source_pack_sha256': source_pack_sha256,
            'sentence_count': len(corpus['sentences']), 'unit_count': len(corpus['units']),
            'entry_count': len(result['proposal']['entries'])}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Write the V73 foundation corpus, inventory and proposal.')
    parser.add_argument('--output', required=True)
    parser.add_argument('--source-pack-sha256', required=True)
    parser.add_argument('--base-declarations', required=True)
    args = parser.parse_args(argv)
    with open(args.base_declarations, 'r', encoding='utf-8') as handle:
        base = json.load(handle)
    receipt = write_outputs(args.output, args.source_pack_sha256, base)
    print(_dumps(receipt))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
