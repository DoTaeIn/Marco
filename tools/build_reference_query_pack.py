'''Offline V74 selected reference-query declaration pack builder.

Reads a qualified source kgpack and an explicit declaration spec, copies every
member and the manifest, and adds a root reference-queries sequence of at most
eight reference-query-ref declaration nodes to the language graph. Existing nodes,
edges, facts, grammar and capabilities stay unchanged; only the graph member bytes
and its manifest hash entry change. Nothing runs at import time.

A declaration may carry an optional ``cue`` object
{literal, fact_rule, candidate_endpoint, query_role, candidate_role}: one graph
reference-cue-pattern (anchor-slot / literal / reference-slot) linked from that
reference-query-ref. The literal is a spec graph asset only; fact_rule, query_role
and candidate_role are actual graph node names validated against the selected
root rule endpoint role and the query known role. Cue nodes are appended after
the old declarations so a cue-free spec yields the old bytes.
'''
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import unicodedata
import zipfile

__all__ = ['ReferenceQueryBuildError', 'build_reference_query_pack', 'build_heterogeneous_reference_pack']

_MAX_PACK_BYTES = 1 << 28
_MAX_SPEC_BYTES = 65536
_MAX_GRAMMAR_BYTES = 65536
_MAX_DECLARATIONS = 8
_MAX_NODES = 512
_MAX_EDGES = 1024
_PREFIX = 'v74_rq_'
_SPEC_SCHEMA = 'marco-reference-query-pack-spec-v1'
_SCOPE = 'graph_declared_single_reference_query_augmentation'
_SHA_RE = re.compile('[0-9a-f]{64}')
_LF = chr(10)
_UNSAFE = (chr(34), '|', '#', chr(10), chr(13))
_DECL_KEYS = ('query_rule', 'form', 'endpoint', 'antecedent_relation', 'antecedent_endpoint')
_CUE_KEYS = ('literal', 'fact_rule', 'candidate_endpoint', 'query_role', 'candidate_role')


class ReferenceQueryBuildError(ValueError):
    '''The inputs are refused; nothing is published.'''


def _fail(message):
    raise ReferenceQueryBuildError(message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


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


def _read(path, cap, label):
    if not os.path.isfile(path):
        _fail('%s is not a regular file' % label)
    with open(path, 'rb') as fh:
        data = fh.read(cap + 1)
    if len(data) > cap:
        _fail('%s exceeds %d bytes' % (label, cap))
    return data


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            _fail('duplicate JSON key %r' % key)
        out[key] = value
    return out


def _refuse(token):
    _fail('unsupported JSON number %r' % token)


def _load_json(data, label):
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        _fail('%s is not UTF-8' % label)
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_refuse, parse_float=_refuse)
    except ReferenceQueryBuildError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ReferenceQueryBuildError('%s is not valid JSON' % label) from exc


def _form_ok(form):
    return (type(form) is str and 1 <= len(form) <= 64 and form == form.strip()
            and not any(unicodedata.category(c).startswith('C') for c in form)
            and not any(c in form for c in _UNSAFE))


def _spec(doc, base_sha):
    if (type(doc) is not dict or set(doc) != {'schema', 'source_pack_sha256', 'declarations'}
            or doc['schema'] != _SPEC_SCHEMA):
        _fail('declaration spec has the wrong shape or schema')
    if doc['source_pack_sha256'] != base_sha:
        _fail('declaration spec is not bound to the source pack')
    rows = doc['declarations']
    if type(rows) is not list or not 1 <= len(rows) <= _MAX_DECLARATIONS:
        _fail('declarations must hold 1..%d entries' % _MAX_DECLARATIONS)
    out, seen = [], set()
    for row in rows:
        if type(row) is not dict or set(row) not in (set(_DECL_KEYS), set(_DECL_KEYS) | {'cue'}):
            _fail('declaration has wrong keys')
        if 'cue' in row:
            cue = row['cue']
            if (type(cue) is not dict
                    or set(cue) not in (set(_CUE_KEYS), set(_CUE_KEYS) | {'continuation_literal'})):
                _fail('declaration cue has wrong keys')
            if 'continuation_literal' in cue:
                cl = cue['continuation_literal']
                if (type(cl) is not str or not 1 <= len(cl) <= 64
                        or any(unicodedata.category(c).startswith('C') for c in cl)
                        or any(c in cl for c in _UNSAFE)):
                    _fail('cue continuation_literal is not usable')
            for key in ('fact_rule', 'query_role', 'candidate_role'):
                if type(cue[key]) is not str or not cue[key]:
                    _fail('cue %s must be a node name' % key)
            lit = cue['literal']
            if (type(lit) is not str or not 1 <= len(lit) <= 64
                    or any(unicodedata.category(c).startswith('C') for c in lit)
                    or any(c in lit for c in _UNSAFE)):
                _fail('cue literal is not usable')
            if type(cue['candidate_endpoint']) is not int or cue['candidate_endpoint'] not in (0, 2):
                _fail('cue candidate_endpoint must be 0 or 2')
            row = dict(row)
            row['cue'] = dict(cue)
        for key in ('query_rule', 'antecedent_relation'):
            if type(row[key]) is not str or not row[key]:
                _fail('declaration %s must be a node name' % key)
        if not _form_ok(row['form']):
            _fail('declaration form is not usable')
        for key in ('endpoint', 'antecedent_endpoint'):
            if type(row[key]) is not int or row[key] not in (0, 2):
                _fail('declaration %s must be 0 or 2' % key)
        mark = (row['query_rule'], row['form'].casefold())
        if mark in seen:
            _fail('declaration repeats a form for one query rule')
        seen.add(mark)
        out.append(dict(row))
    return out


class _Graph:
    def __init__(self, g):
        self.g = g
        self.nodes = g.get('공통층')
        self.edges = g.get('엣지')
        if type(self.nodes) is not dict or type(self.edges) is not list:
            _fail('language graph lacks common nodes or edges')
        self.taken = set()
        for layer in ('공통층', '사례층', '무관층'):
            self.taken.update(g.get(layer) or {})
        if any(name.startswith(_PREFIX) for name in self.taken):
            _fail('base graph already holds V74 reference-query names')
        sources = {e[0] for e in self.edges}
        self.values = {}
        for name, ex in self.nodes.items():
            if (type(ex) is list and len(ex) == 1 and type(ex[0]) is str and name not in sources
                    and (ex[0].startswith(('s=', 'i=')) or ex[0] in ('b=true', 'b=false'))):
                self.values.setdefault(ex[0], name)
        self.count = 0

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
        if type(value) is int:
            encoded = 'i=%d' % value
        elif type(value) is str and value and not any(c in value for c in _UNSAFE):
            encoded = 's=' + value
        else:
            _fail('graph scalar is not writable')
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


def _underspecified(graph, root, members):
    refs = graph.targets(root, 'grammar-ref')
    if len(refs) != 1:
        return set()
    path = graph.scalar(graph.link(refs[0], 'member-path'))
    sha = graph.scalar(graph.link(refs[0], 'sha256'))
    data = members.get(path)
    if type(data) is not bytes or len(data) > _MAX_GRAMMAR_BYTES or type(sha) is not str or _sha(data) != sha:
        _fail('grammar member missing or digest mismatch')
    doc = _load_json(data, 'grammar')
    pack = doc.get('language_pack') if type(doc) is dict else None
    refs = pack.get('references') if type(pack) is dict else None
    forms = refs.get('underspecified_forms') if type(refs) is dict else None
    return {f.casefold() for f in forms if type(f) is str} if type(forms) is list else set()


def _assemble(graph, root, decls, members):
    if graph.op(root) != 'root':
        _fail('language root is not op=root')
    if graph.targets(root, 'reference-queries'):
        _fail('base graph already declares reference queries')
    seqs = graph.targets(root, 'queries')
    if len(seqs) != 1:
        _fail('base root declares no unique queries sequence')
    rules = [graph.link(item, 'target') for item in graph.sequence(seqs[0])]
    if not graph.targets(root, 'question-marks'):
        _fail('base root declares no question marks')
    blocked = _underspecified(graph, root, members)
    refs, cues = [], []
    for k, d in enumerate(decls):
        rule = d['query_rule']
        if rule not in rules or graph.op(rule) != 'query-rule':
            _fail('query_rule %r is not a selected root query rule' % rule)
        emits = graph.link(rule, 'emits')
        if graph.op(emits) != 'query-meaning':
            _fail('query rule emits no query-meaning')
        subject, obj, asked = (graph.link(emits, r) for r in ('subject', 'object', 'asked'))
        if asked == subject:
            known = obj
        elif asked == obj:
            known = subject
        else:
            _fail('query asked role is not subject or object')
        if d['endpoint'] != (0 if known == subject else 2):
            _fail('declaration endpoint is not the bound query endpoint')
        sense = d['antecedent_relation']
        if sense not in graph.nodes or graph.nodes[sense] != ['n=null'] or graph.op(sense) != 'sense':
            _fail('antecedent_relation %r is not a common-layer sense' % sense)
        if d['form'].casefold() in blocked:
            _fail('declaration form is an underspecified form')
        if 'cue' in d:
            cues.append((k, d['cue'], known))
        ref = graph.node('ref%d' % k, 'reference-query-ref')
        graph.edge(ref, 'query-rule', rule)
        graph.edge(ref, 'form', graph.value(d['form']))
        graph.edge(ref, 'endpoint', graph.value(d['endpoint']))
        graph.edge(ref, 'antecedent-relation', sense)
        graph.edge(ref, 'antecedent-endpoint', graph.value(d['antecedent_endpoint']))
        refs.append(ref)
    seq = graph.node('sequence', 'sequence')
    prev = None
    for ref in refs:
        graph.edge(seq if prev is None else prev, 'first' if prev is None else 'next', ref)
        prev = ref
    graph.edge(root, 'reference-queries', seq)
    if cues:
        rule_seqs = graph.targets(root, 'rules')
        if len(rule_seqs) != 1:
            _fail('base root declares no unique rules sequence')
        facts = [graph.link(item, 'target') for item in graph.sequence(rule_seqs[0])]
    # Preserve existing cue node/scalar allocation before adding continuation-capable definitions.
    ordered_cues = sorted(cues, key=lambda row: 'continuation_literal' in row[1])
    for j, (k, cue, known) in enumerate(ordered_cues):
        rule = cue['fact_rule']
        if rule not in facts or graph.op(rule) != 'rule':
            _fail('cue fact_rule %r is not a selected root rule' % rule)
        emits = graph.link(rule, 'emits')
        if graph.op(emits) != 'meaning':
            _fail('cue fact rule emits no meaning')
        pol = graph.targets(emits, 'polarity')
        if pol and (len(pol) != 1 or graph.scalar(pol[0]) is not True):
            _fail('cue fact rule is not positive')
        subs = graph.sequence(graph.link(emits, 'subjects'))
        if len(subs) != 1:
            _fail('cue fact rule needs one subject role')
        ce = cue['candidate_endpoint']
        actual = graph.link(subs[0], 'target') if ce == 0 else graph.link(emits, 'object')
        if cue['candidate_role'] != actual:
            _fail('cue candidate_role is not the actual frame endpoint role')
        if cue['query_role'] != known:
            _fail('cue query_role is not the actual query known role')
        for role in (cue['candidate_role'], cue['query_role']):
            if graph.op(role) != 'role':
                _fail('cue role %r is not op=role' % role)
        node = graph.node('cue%d' % j, 'reference-cue-pattern')
        reads = graph.node('cue%d_reads' % j, 'sequence')
        anchor = graph.node('cue%d_anchor' % j, 'anchor-slot')
        lit = graph.node('cue%d_literal' % j, 'literal')
        refslot = graph.node('cue%d_reference' % j, 'reference-slot')
        graph.edge(lit, 'value', graph.value(cue['literal']))
        graph.edge(reads, 'first', anchor)
        graph.edge(anchor, 'next', lit)
        graph.edge(lit, 'next', refslot)
        graph.edge(node, 'reads', reads)
        graph.edge(node, 'fact-rule', rule)
        graph.edge(node, 'candidate-endpoint', graph.value(ce))
        graph.edge(node, 'query-role', cue['query_role'])
        graph.edge(node, 'candidate-role', cue['candidate_role'])
        if 'continuation_literal' in cue:
            graph.edge(node, 'continuation-literal', graph.value(cue['continuation_literal']))
        graph.edge(refs[k], 'cue-pattern', node)
    return len(refs)


_BUNDLE_SCHEMA = 'marco-graph-vm-program-bundle-v1'
_PROGRAM_NAME = 'reference-clauses'
_ANCHOR_NAME = 'scoped-conditions'
_REF_MEMBER = 'programs/reference-clauses.json'
_BUNDLE_MEMBER = 'programs/scoped-conditions-reference.bundle.json'
_COND_RAW_SHA = '89b62a96aa0d8d0593367e93bed121a0c4530551a52023031b06c22826aabbed'
_COND_CANON_SHA = 'fc6e2ddc61ccbd5433435e417895c7e6d1d322b538228ae693e7e7253364667d'
_MAX_PROGRAM_BYTES = 65536


def _canon_sha(value):
    return _sha(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))


def _program_inputs(ref_path, ref_sha, bundle_path, bundle_sha):
    for value in (ref_sha, bundle_sha):
        if type(value) is not str or not _SHA_RE.fullmatch(value):
            _fail('program sha256 must be 64 lowercase hex')
    rb = _read(_path(ref_path, 'reference program'), _MAX_PROGRAM_BYTES, 'reference program')
    bb = _read(_path(bundle_path, 'program bundle'), _MAX_PROGRAM_BYTES, 'program bundle')
    if _sha(rb) != ref_sha or _sha(bb) != bundle_sha:
        _fail('program file sha256 mismatch')
    from marco.reasoning import graph_vm
    try:
        program = graph_vm.validate_program(_load_json(rb, 'reference program'))
        bundle = _load_json(bb, 'program bundle')
        if (type(bundle) is not dict or set(bundle) != {'schema', 'entries'}
                or bundle['schema'] != _BUNDLE_SCHEMA or type(bundle['entries']) is not list
                or not 1 <= len(bundle['entries']) <= 16):
            _fail('program bundle has the wrong shape')
        names = {}
        for row in bundle['entries']:
            if (type(row) is not dict or set(row) != {'name', 'program'} or type(row['name']) is not str
                    or not row['name'] or row['name'] in names):
                _fail('program bundle entry is malformed')
            names[row['name']] = graph_vm.validate_program(row['program'])
    except ReferenceQueryBuildError:
        raise
    except ValueError as exc:
        raise ReferenceQueryBuildError('program asset is invalid: %s' % exc) from exc
    return rb, bb, program, names


def _rewire(graph, root, members, inputs):
    rb, bb, program, names = inputs
    if set(names) != {_ANCHOR_NAME, _PROGRAM_NAME}:
        _fail('bundle must hold exactly the conditions and reference-clauses programs')
    if _canon_sha(names[_PROGRAM_NAME]) != _canon_sha(program):
        _fail('bundle reference-clauses program differs from the raw program')
    if _REF_MEMBER in members or _BUNDLE_MEMBER in members:
        _fail('base pack already holds the new program members')
    seqs = graph.targets(root, 'programs')
    if len(seqs) != 1:
        _fail('base root declares no unique programs sequence')
    refs = graph.sequence(seqs[0])
    labels = [graph.scalar(graph.link(r, 'name')) for r in refs]
    if labels.count(_ANCHOR_NAME) != 1 or _PROGRAM_NAME in labels:
        _fail('program reference names are not as expected')
    ref = refs[labels.index(_ANCHOR_NAME)]
    path = graph.scalar(graph.link(ref, 'member-path'))
    sha = graph.scalar(graph.link(ref, 'sha256'))
    old = members.get(path)
    if old is None or _sha(old) != sha or sha != _COND_RAW_SHA:
        _fail('conditions raw member is not the baseline')
    if (_canon_sha(_load_json(old, 'conditions program')) != _COND_CANON_SHA
            or _canon_sha(names[_ANCHOR_NAME]) != _COND_CANON_SHA):
        _fail('conditions program differs from the baseline')
    leaves = {'member-path': graph.value(_BUNDLE_MEMBER), 'sha256': graph.value(_sha(bb)),
              'schema': graph.value(_BUNDLE_SCHEMA)}
    changes = []
    for rel, leaf in leaves.items():
        idx = [i for i, e in enumerate(graph.edges) if e[0] == ref and e[1] == rel]
        if len(idx) != 1:
            _fail('conditions reference edge %s is not unique' % rel)
        graph.edges[idx[0]][2] = leaf
        changes.append((idx[0], leaf))
    return changes


def _projection_budget(graph, root):
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
    if len(nodes) > _MAX_NODES or len(edges) > _MAX_EDGES:
        _fail('derived language graph exceeds projection node/edge budgets')
    return len(nodes), len(edges)


def build_reference_query_pack(source_pack, spec_path, output, *, expected_base_sha256,
                              reference_program_path=None, reference_program_sha256=None,
                              program_bundle_path=None, program_bundle_sha256=None):
    '''Build a new pack from source_pack plus the explicit declaration spec; return a receipt.'''
    if type(expected_base_sha256) is not str or not _SHA_RE.fullmatch(expected_base_sha256):
        _fail('expected_base_sha256 must be 64 lowercase hex')
    src = _path(source_pack, 'source pack')
    spath = _path(spec_path, 'declaration spec')
    dst = _path(output, 'output')
    if len({src, spath, dst}) != 3:
        _fail('input and output paths must be distinct')
    parent = os.path.dirname(dst)
    if os.path.lexists(dst) or not os.path.isdir(parent):
        _fail('output must be a new path in an existing directory')
    reals = [os.path.realpath(p) for p in (src, spath)]
    if len(set(reals)) != 2 or os.path.realpath(dst) in reals:
        _fail('invalid input/output relation')
    if _sha(_read(src, _MAX_PACK_BYTES, 'source pack')) != expected_base_sha256:
        _fail('source pack sha256 mismatch')
    spec_bytes = _read(spath, _MAX_SPEC_BYTES, 'declaration spec')
    spec_sha = _sha(spec_bytes)
    decls = _spec(_load_json(spec_bytes, 'declaration spec'), expected_base_sha256)
    given = [reference_program_path, reference_program_sha256, program_bundle_path, program_bundle_sha256]
    wants = any('continuation_literal' in d.get('cue', {}) for d in decls)
    if any(v is not None for v in given) and any(v is None for v in given):
        _fail('program kwargs must be all present or all None')
    if wants and any(v is None for v in given):
        _fail('continuation policy requires all four program kwargs')
    program_inputs = _program_inputs(*given) if given[0] is not None else None

    from marco.storage import graph_text, kgpack

    try:
        manifest, members = kgpack.read(src)
    except kgpack.KGPackError as exc:
        raise ReferenceQueryBuildError('source pack unreadable: %s' % exc) from exc
    if _sha(_read(src, _MAX_PACK_BYTES, 'source pack')) != expected_base_sha256:
        _fail('source pack changed while reading')
    model = manifest.get('model')
    language = model.get('language_graph') if isinstance(model, dict) else None
    if not isinstance(language, dict):
        _fail('source pack declares no language graph')
    member, root = language.get('member_path'), language.get('root')
    if type(member) is not str or type(root) is not str or member not in members:
        _fail('source language graph member is missing')
    try:
        g = graph_text.parse(members[member], member)
    except graph_text.GraphTextError as exc:
        raise ReferenceQueryBuildError('source graph unreadable: %s' % exc) from exc
    old_nodes = copy.deepcopy(g.get('공통층'))
    old_edges = copy.deepcopy(g.get('엣지'))
    graph = _Graph(g)
    count = _assemble(graph, root, decls, members)
    changes = _rewire(graph, root, members, program_inputs) if program_inputs is not None else []
    budget = _projection_budget(graph, root)
    try:
        new_graph = graph_text.write(g, member).encode('utf-8')
        check = graph_text.parse(new_graph, member)
    except graph_text.GraphTextError as exc:
        raise ReferenceQueryBuildError('assembled graph is not writable: %s' % exc) from exc
    if check['공통층'] != g['공통층'] or check['엣지'] != g['엣지']:
        _fail('assembled graph does not read back equal')
    for name, examples in old_nodes.items():
        if check['공통층'].get(name) != examples:
            _fail('original graph node changed')
    expected_edges = copy.deepcopy(old_edges)
    for i, target_leaf in changes:
        expected_edges[i][2] = target_leaf
    if [list(e) for e in check['엣지'][:len(old_edges)]] != [list(e) for e in expected_edges]:
        _fail('original graph edges changed')

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
    if program_inputs is not None:
        for extra_path, extra_data in ((_REF_MEMBER, program_inputs[0]), (_BUNDLE_MEMBER, program_inputs[1])):
            members2[extra_path] = extra_data
            manifest2['files'].append({'path': extra_path, 'kind': 'asset', 'bytes': len(extra_data),
                                       **kgpack.content_identity(extra_data)})
        manifest2['files'].sort(key=lambda x: x['path'])
    mbytes = (json.dumps(manifest2, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
              + _LF).encode('utf-8')
    fd, tmp = tempfile.mkstemp(prefix='.v74-reference-', suffix='.tmp', dir=parent)
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
            raise ReferenceQueryBuildError('built pack does not verify: %s' % exc) from exc
        if m2 != manifest2 or d2 != members2:
            _fail('built pack does not match the expected content')
        for name, body in members.items():
            if name != member and d2.get(name) != body:
                _fail('preserved member changed: %s' % name)
        with open(tmp, 'rb') as fh:
            out = fh.read()
        for value, label in ((src, 'source pack'), (spath, 'declaration spec'), (dst, 'output')):
            _path(value, label)
        if (_sha(_read(src, _MAX_PACK_BYTES, 'source pack')) != expected_base_sha256
                or _sha(_read(spath, _MAX_SPEC_BYTES, 'declaration spec')) != spec_sha):
            _fail('input bytes changed before publication')
        if os.path.lexists(dst):
            _fail('output already exists')
        try:
            os.link(tmp, dst)
        except FileExistsError:
            _fail('output already exists')
        except OSError as exc:
            raise ReferenceQueryBuildError('exclusive publication failed: %s' % exc) from exc
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return {'output_path': dst, 'sha256': _sha(out), 'bytes': len(out), 'spec_sha256': spec_sha,
            'base_sha256': expected_base_sha256, 'declaration_count': count,
            'projection_nodes': budget[0], 'projection_edges': budget[1], 'scope': _SCOPE,
            **({'programs_installed': [_REF_MEMBER, _BUNDLE_MEMBER]} if program_inputs is not None else {})}


_HET_SCHEMA = 'marco-heterogeneous-reference-graph-spec-v1'
_HET_MERGE_OPS = frozenset(('sequence', 'scalar', 'literal', 'predicate', 'slot', 'role-ref', 'rule-ref',
                            'query-ref', 'reply-ref', 'reference-cue-ref', 'anchor-slot', 'reference-slot',
                            'meaning', 'query-meaning'))
_HET_IDENT_RELS = frozenset(('target', 'role', 'relation', 'object', 'subject', 'asked', 'query-rule',
                             'fact-rule', 'query-role', 'candidate-role', 'antecedent-relation',
                             'negative-rule', 'positive-rule', 'predicate', 'case-group', 'type-ref'))


def _het_name_ok(name):
    return (type(name) is str and bool(name) and name[0] != '-'
            and all(c.isalnum() or c in '_-' for c in name))


def _het_compact(g, root):
    '''Bottom-up DAG hash-cons of pure auxiliary nodes by exact full outgoing signature; returns removed count.'''
    layers = [k for k in ('공통층', '사례층', '무관층') if isinstance(g.get(k), dict)]
    nodes, where = {}, {}
    for k in layers:
        for n, ex in g[k].items():
            nodes[n] = ex
            where[n] = k
    out = {}
    for a, r, b in g['엣지']:
        out.setdefault(a, []).append((r, b))

    def op_of(n):
        for r, d in out.get(n, ()):
            if r == 'op':
                ex = nodes.get(d)
                if ex and len(ex) == 1 and ex[0].startswith('s='):
                    return ex[0][2:]
        return None
    protected = {b for a, r, b in g['엣지'] if r in _HET_IDENT_RELS}
    protected.add(root)
    canon, sigs, active = {}, {}, set()

    def visit(n):
        if n in canon:
            return canon[n]
        if n in active:
            _fail('language graph contains a cycle at %r; compaction refused' % n)
        active.add(n)
        edges = tuple((r, visit(d) if d in nodes else d) for r, d in out.get(n, ()))
        active.discard(n)
        ex = nodes.get(n)
        leaf = (not out.get(n) and ex is not None and len(ex) == 1 and ex[0][:2] in ('s=', 'i=', 'b=', 'n='))
        ok = ex is not None and n not in protected and (leaf or op_of(n) in _HET_MERGE_OPS)
        if ok:
            canon[n] = sigs.setdefault((tuple(ex), edges), n)
        else:
            canon[n] = n
        return canon[n]
    for n in list(nodes):
        visit(n)
    rows = []
    for a, r, b in g['엣지']:
        if canon.get(a, a) != a:
            continue
        rows.append([a, r, canon.get(b, b)])
    g['엣지'] = rows
    removed = 0
    for n, c in canon.items():
        if c != n:
            del g[where[n]][n]
            removed += 1
    return removed


def build_heterogeneous_reference_pack(source_pack, spec_path, output, *, expected_base_sha256):
    '''Build a NEW pack: clone of the V76 pack plus the spec graph additions, compacted into a new graph member.

    Spec (strict JSON, marco-heterogeneous-reference-graph-spec-v1): {schema, source_pack_sha256, member_path
    (new graphs/*.kg), nodes: {name: example-string}, edges: [[src, relation, dst], ...]}. All words live in the spec.'''
    if type(expected_base_sha256) is not str or not _SHA_RE.fullmatch(expected_base_sha256):
        _fail('expected_base_sha256 must be 64 lowercase hex')
    src = _path(source_pack, 'source pack')
    spath = _path(spec_path, 'heterogeneous spec')
    dst = _path(output, 'output')
    if len({src, spath, dst}) != 3:
        _fail('input and output paths must be distinct')
    parent = os.path.dirname(dst)
    if os.path.lexists(dst) or not os.path.isdir(parent):
        _fail('output must be a new path in an existing directory')
    reals = [os.path.realpath(p) for p in (src, spath)]
    if len(set(reals)) != 2 or os.path.realpath(dst) in reals:
        _fail('invalid input/output relation')
    if _sha(_read(src, _MAX_PACK_BYTES, 'source pack')) != expected_base_sha256:
        _fail('source pack sha256 mismatch')
    spec_bytes = _read(spath, 262144, 'heterogeneous spec')
    spec_sha = _sha(spec_bytes)
    spec = _load_json(spec_bytes, 'heterogeneous spec')
    if (type(spec) is not dict or set(spec) != {'schema', 'source_pack_sha256', 'member_path', 'nodes', 'edges'}
            or spec['schema'] != _HET_SCHEMA or spec['source_pack_sha256'] != expected_base_sha256):
        _fail('heterogeneous spec has the wrong shape, schema or base binding')
    nodes, edges, member_new = spec['nodes'], spec['edges'], spec['member_path']
    if (type(nodes) is not dict or not 1 <= len(nodes) <= _MAX_NODES or type(edges) is not list
            or not 1 <= len(edges) <= _MAX_EDGES or type(member_new) is not str):
        _fail('heterogeneous spec lists are malformed or over budget')
    for name, ex in nodes.items():
        if (not _het_name_ok(name) or type(ex) is not list or len(ex) != 1 or type(ex[0]) is not str
                or any(c in ex[0] for c in ('"', '|', '#', chr(10), chr(13)))):
            _fail('spec node %r is not writable' % (name,))
    for row in edges:
        if (type(row) is not list or len(row) != 3 or not all(_het_name_ok(x) for x in row)):
            _fail('spec edge is malformed')
    from marco.storage import graph_text, kgpack
    try:
        kgpack._safe_path(member_new)
    except kgpack.KGPackError as exc:
        raise ReferenceQueryBuildError('unsafe member_path') from exc
    if not member_new.startswith('graphs/') or not member_new.endswith('.kg'):
        _fail('member_path must be a new graphs/*.kg path')
    try:
        manifest, members = kgpack.read(src)
    except kgpack.KGPackError as exc:
        raise ReferenceQueryBuildError('source pack unreadable: %s' % exc) from exc
    if _sha(_read(src, _MAX_PACK_BYTES, 'source pack')) != expected_base_sha256:
        _fail('source pack changed while reading')
    model = manifest.get('model')
    language = model.get('language_graph') if isinstance(model, dict) else None
    if not isinstance(language, dict):
        _fail('source pack declares no language graph')
    member, root = language.get('member_path'), language.get('root')
    if type(member) is not str or type(root) is not str or member not in members or member_new in members:
        _fail('source language graph member missing or new member path already used')
    try:
        g = graph_text.parse(members[member], member)
    except graph_text.GraphTextError as exc:
        raise ReferenceQueryBuildError('source graph unreadable: %s' % exc) from exc
    taken = set()
    for layer in ('공통층', '사례층', '무관층'):
        taken.update(g.get(layer) or {})
    if taken & set(nodes):
        _fail('spec node names collide with the base graph')
    for name, ex in nodes.items():
        g['공통층'][name] = [ex[0]]
    known = taken | set(nodes)
    for a, r, b in edges:
        if a not in known or b not in known:
            _fail('spec edge names an unknown node')
        g['엣지'].append([a, r, b])
    # Extend only positive fact authority for newly appended graph rules; retain old raw grammar member.
    def one_target(node, relation):
        values = [b for a, rel, b in g['엣지'] if a == node and rel == relation]
        if len(values) != 1:
            _fail('heterogeneous graph requires one %s edge' % relation)
        return values[0]
    def text_value(node):
        values = g['공통층'].get(node)
        if type(values) is not list or len(values) != 1 or not values[0].startswith('s='):
            _fail('heterogeneous graph requires a text scalar')
        return values[0][2:]
    sequence = one_target(root, 'rules')
    starts = [b for a, rel, b in g['엣지'] if a == sequence and rel == 'first']
    if len(starts) != 1:
        _fail('heterogeneous rule sequence lacks first')
    rule_order, visited, cursor = [], set(), starts[0]
    while cursor is not None:
        if cursor in visited:
            _fail('heterogeneous rule sequence cycles')
        visited.add(cursor)
        rule_order.append(one_target(cursor, 'target'))
        nexts = [b for a, rel, b in g['엣지'] if a == cursor and rel == 'next']
        if len(nexts) > 1:
            _fail('heterogeneous rule sequence has duplicate next')
        cursor = nexts[0] if nexts else None
    added_indices = [i for i, rule in enumerate(rule_order) if rule in nodes]
    if not added_indices:
        _fail('heterogeneous declaration has no new fact rules')
    grammar_node = one_target(root, 'grammar-ref')
    old_grammar_path = text_value(one_target(grammar_node, 'member-path'))
    if old_grammar_path not in members:
        _fail('active grammar member absent')
    old_grammar = _load_json(members[old_grammar_path], 'active grammar')
    new_grammar = copy.deepcopy(old_grammar)
    caps = new_grammar.get('semantic_capabilities')
    positive = caps.get('conditional_binary') if type(caps) is dict else None
    indices = positive.get('frame_indices') if type(positive) is dict else None
    if (type(indices) is not list or not all(type(i) is int and 0 <= i < len(rule_order) for i in indices)
            or len(set(indices)) != len(indices)):
        _fail('active positive fact authority is malformed')
    positive['frame_indices'] = indices + [i for i in added_indices if i not in indices]
    if len(positive['frame_indices']) > 16:
        _fail('positive fact authority exceeds existing frame limit')
    grammar_bytes = (json.dumps(new_grammar, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + _LF).encode('utf-8')
    grammar_new = 'grammars/' + os.path.basename(member_new)[:-3] + '-scoped.json'
    if grammar_new in members:
        _fail('new grammar path already present')
    for relation, value in (('member-path', grammar_new), ('sha256', _sha(grammar_bytes))):
        leaf = 'het_grammar_' + relation.replace('-', '_')
        if leaf in known:
            _fail('new grammar scalar name collides')
        g['공통층'][leaf] = ['s=' + value]
        for edge in g['엣지']:
            if edge[0] == grammar_node and edge[1] == relation:
                edge[2] = leaf
    removed = _het_compact(g, root)
    holder = type('GraphEdges', (), {})()
    holder.edges = g['엣지']
    budget = _projection_budget(holder, root)
    try:
        new_graph = graph_text.write(g, member_new).encode('utf-8')
    except graph_text.GraphTextError as exc:
        raise ReferenceQueryBuildError('assembled graph is not writable: %s' % exc) from exc
    manifest2 = copy.deepcopy(manifest)
    manifest2['model']['language_graph']['member_path'] = member_new
    manifest2['files'].append({'path': member_new, 'kind': 'graph', 'bytes': len(new_graph),
                               **kgpack.content_identity(new_graph)})
    manifest2['files'].sort(key=lambda x: x['path'])
    members2 = dict(members)
    members2[member_new] = new_graph
    members2[grammar_new] = grammar_bytes
    manifest2['files'].append({'path': grammar_new, 'kind': 'asset', 'bytes': len(grammar_bytes), **kgpack.content_identity(grammar_bytes)})
    manifest2['files'].sort(key=lambda x: x['path'])
    mbytes = (json.dumps(manifest2, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
              + _LF).encode('utf-8')
    fd, tmp = tempfile.mkstemp(prefix='.v77-heterogeneous-', suffix='.tmp', dir=parent)
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
            raise ReferenceQueryBuildError('built pack does not verify: %s' % exc) from exc
        if m2 != manifest2 or d2 != members2:
            _fail('built pack does not match the expected content')
        for name, body in members.items():
            if d2.get(name) != body:
                _fail('preserved member changed: %s' % name)
        with open(tmp, 'rb') as fh:
            out = fh.read()
        if (_sha(_read(src, _MAX_PACK_BYTES, 'source pack')) != expected_base_sha256
                or _sha(_read(spath, 262144, 'heterogeneous spec')) != spec_sha):
            _fail('input bytes changed before publication')
        if os.path.lexists(dst):
            _fail('output already exists')
        try:
            os.link(tmp, dst)
        except FileExistsError:
            _fail('output already exists')
        except OSError as exc:
            raise ReferenceQueryBuildError('exclusive publication failed: %s' % exc) from exc
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return {'output_path': dst, 'sha256': _sha(out), 'bytes': len(out), 'spec_sha256': spec_sha,
            'base_sha256': expected_base_sha256, 'language_member': member_new, 'merged_nodes': removed,
            'projection_nodes': budget[0], 'projection_edges': budget[1],
            'grammar_member': grammar_new, 'positive_frame_indices_added': added_indices}
