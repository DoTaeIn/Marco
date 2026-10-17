# -*- coding: utf-8 -*-
"""뜻풀이의 틀을 손으로 적지 않고 이미 있는 사례에서 꺼낸다.

뜻풀이의 몸통은 **보통 문장**이다. 다만 사건이 채울 자리가 비어 있을 뿐이다.

    치우다는 [     ] 물건을 상자로 옮기는 것이다
    하루가       연필을        치웠다

그래서 몸통은 **앞자리를 지운 사례**에 맞춰 읽고, 비어 있던 자리는 사건이
**같은 조사로** 채운다. 짜임이 하나 늘 때마다 틀을 새로 선언하지 않는다.

여기서 선언에 기대는 것은 둘뿐이고, 둘 다 낱말마다 늘지 않는다.

* 조사 — 닫힌 낱말갈래다. 한국어의 조사는 세다가 끝난다.
* 이미 적혀 있는 보통 문장 사례 — 틀이 아니라 문장이다.

그래서 못 읽는 뜻풀이가 남는다면 그것은 **틀이 없어서가 아니라 몸통의 동사를
모르기 때문**이다. 이 둘은 값이 다르다. 틀은 끝없이 늘고 동사는 유한하다.
"""
from copy import deepcopy

from marco.language.hangul import inflect
from relational_semantics import asserted, substitute


_MAX_SOURCE, _MAX_TOKENS, _MAX_ITEMS = 512, 40, 64


def _compile_seed_predicate(parser, declaration, frame):
    """Compile one seed-bound predicate frame into a detached canonical record."""
    import hashlib
    import json
    import re

    def bad(reason):
        raise ValueError("seed_predicate_" + reason)

    def strict_int(value):
        return isinstance(value, int) and not isinstance(value, bool)

    def text_ok(value):
        return isinstance(value, str) and bool(value)

    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode()).hexdigest()

    if not isinstance(declaration, dict) or not isinstance(frame, dict):
        bad("malformed_input")
    data = getattr(parser, "data", None)
    examples = data.get("examples") if isinstance(data, dict) else None
    if not isinstance(examples, list):
        bad("missing_examples")
    count, declared = declaration.get("seed_count"), declaration.get("seed_sha256")
    if not strict_int(count) or not 1 <= count <= len(examples):
        bad("bad_seed_count")
    if not isinstance(declared, str) or not re.fullmatch(r"[0-9a-f]{64}", declared):
        bad("bad_seed_sha256")
    ref = frame.get("source_ref")
    if not isinstance(ref, dict):
        bad("bad_source_ref")
    index, ann_sha = ref.get("index"), ref.get("annotation_sha256")
    if not strict_int(index) or not 0 <= index < count:
        bad("source_index_outside_seed_prefix")
    if not isinstance(ann_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", ann_sha):
        bad("bad_annotation_sha256")
    annotation = examples[index]
    if digest(examples[:count]) != declared:
        bad("seed_digest_mismatch")
    if digest(annotation) != ann_sha:
        bad("annotation_digest_mismatch")

    # Shape of the selected annotation.
    if not isinstance(annotation, dict):
        bad("bad_annotation")
    text, slots, meaning = annotation.get("text"), annotation.get("slots"), annotation.get("meaning")
    if not text_ok(text):
        bad("bad_text")
    if not isinstance(slots, dict) or len(slots) not in (2, 3):
        bad("bad_slots")
    for name, value in slots.items():
        if not text_ok(name) or not text_ok(value):
            bad("bad_slots")
    occurrences = []
    for name, value in slots.items():
        found = [i for i in range(len(text)) if text.startswith(value, i)]
        if len(found) != 1:
            bad("slot_literal_not_unique")
        occurrences.append((found[0], found[0] + len(value)))
    occurrences.sort()
    if any(occurrences[i][1] > occurrences[i + 1][0] for i in range(len(occurrences) - 1)) \
            or len(set(slots.values())) != len(slots):
        bad("slot_literals_overlap")
    scalar_names = [n for n, v in slots.items() if v.isdecimal()]
    if len(slots) == 3 and len(scalar_names) != 1:
        bad("bad_slots")
    if not isinstance(meaning, dict) or "triple" not in meaning \
            or not set(meaning) <= {"triple", "polarity", "modality"}:
        bad("bad_meaning")
    triple = meaning["triple"]
    if len(slots) == 3:
        if not isinstance(triple, list) or len(triple) != 3:
            bad("bad_triple")
        subject, relation, last = triple
        if not isinstance(subject, list) or len(subject) != 2 or not all(text_ok(t) for t in subject) \
                or not text_ok(relation) or not text_ok(last):
            bad("bad_triple")
        scalar_ref = "$" + scalar_names[0]
        ref_names = {"$" + n for n in slots if n != scalar_names[0]}
        if len(set(subject)) != 2 or set(subject) != ref_names or last != scalar_ref:
            bad("bad_triple_references")
        if relation.startswith("$"):
            bad("relation_is_placeholder")
    else:
        if not isinstance(triple, list) or len(triple) != 3 or not all(text_ok(t) for t in triple):
            bad("bad_triple")
        first, relation, last = triple
        declared_refs = {"$" + name for name in slots}
        if first == last or first not in declared_refs or last not in declared_refs:
            bad("bad_triple_references")
        if relation.startswith("$"):
            bad("relation_is_placeholder")
    if "polarity" in meaning and not isinstance(meaning["polarity"], bool):
        bad("bad_polarity")
    if "modality" in meaning and meaning["modality"] not in ("asserted", "planned", "conditional"):
        bad("bad_modality")

    span = frame.get("predicate_span")
    if not isinstance(span, list) or len(span) != 2 or not all(strict_int(v) for v in span):
        bad("bad_predicate_span")
    start, end = span
    if not 0 <= start < end <= len(text):
        bad("bad_predicate_span")
    if any(start < hi and lo < end for lo, hi in occurrences):
        bad("predicate_span_intersects_slot")

    # A boundary may not cut fixed (no-slot) lexical material.
    chunks, tail, tail_slots = _chunks(annotation, parser.case_particles, parser.slot_particles)
    cursor, pieces = 0, []
    for chunk_text, inside in chunks:
        lo = text.index(chunk_text, cursor)
        cursor = lo + len(chunk_text)
        pieces.append((lo, cursor, inside))
    if tail:
        lo = text.index(tail, cursor)
        pieces.append((lo, lo + len(tail), tail_slots))
    for lo, hi, inside in pieces:
        if not inside and (lo < start < hi or lo < end < hi):
            bad("predicate_span_cuts_fixed_chunk")

    canonical = text[start:end]
    forms = [{"text": canonical, "inflection": None}]
    for surface, suffix, trace in parser._inflected_examples(annotation):
        if not text_ok(suffix) or not canonical.endswith(suffix):
            bad("inflection_suffix_not_in_predicate")
        forms.append({"text": canonical[:-len(suffix)] + surface,
                      "inflection": deepcopy(trace)})
    return {"annotation": deepcopy(annotation), "source_ref": deepcopy(ref),
            "seed_count": count, "seed_sha256": declared,
            "canonical_predicate": canonical, "forms": forms}

def _selected_reference_forms(parser):
    """Resolve the optional selected reference_forms declaration (pure); None if absent/unusable."""
    import hashlib
    import json
    import re

    data = getattr(parser, "data", None)
    frames = data.get("predicate_frames") if isinstance(data, dict) else None
    decl = frames.get("reference_forms") if isinstance(frames, dict) else None
    if decl is None:
        return None

    def bad(msg):
        raise ValueError("selected reference forms: " + msg)

    refs = {"owner_pattern_ref", "owner_suffixes_ref", "nominal_tails_ref"}
    if not isinstance(decl, dict) or set(decl) != refs | {"schema", "construction"} \
            or decl["schema"] != "selected-reference-forms-v1" or decl["construction"] != "owner_nominal_tail":
        bad("declaration")
    approved = {"owner_pattern_ref": ["holder_forms", "name"],
                "owner_suffixes_ref": ["holder_forms", "possessive_suffix"],
                "nominal_tails_ref": ["holder_forms", "relation_nouns"]}
    if any(decl[k] != v for k, v in approved.items()):
        bad("pointer")
    holder = getattr(parser, "holder_forms", None)
    if not isinstance(holder, dict) or any(v[1] not in holder for v in approved.values()):
        bad("holder_forms")
    name, sufs, tails = (holder[approved[k][1]] for k in ("owner_pattern_ref", "owner_suffixes_ref", "nominal_tails_ref"))
    if not isinstance(name, str) or not name.strip():
        bad("owner pattern")
    if not isinstance(sufs, list) or not sufs or len(set(sufs)) != len(sufs) \
            or any(not isinstance(s, str) or re.search(r"\s", s) for s in sufs):
        bad("owner suffixes")
    if not isinstance(tails, list) or not tails or len(set(tails)) != len(tails) or any(
            not isinstance(t, str) or not t or t != t.strip() or re.search(r"\s{2,}|[^\S ]", t) for t in tails):
        bad("nominal tails")
    try:
        rx = re.compile(name, re.IGNORECASE if data.get("ignore_case") else 0)
    except re.error:
        bad("owner pattern")
    if rx.fullmatch(""):
        bad("owner pattern empty")
    digest = hashlib.sha256(json.dumps([name, sufs, tails], separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return {"name": rx, "suffixes": list(sufs), "tails": list(tails), "sha256": digest,
            "ignore_case": isinstance(data, dict) and bool(data.get("ignore_case"))}


def _reference_span_ok(ref, text, atom_ok, blocked, source=None, span=None):
    """Exact original-source span acceptance: atomic head, or owner[+suffix] + one space + selected tail."""
    import re
    if not isinstance(text, str) or not text or not isinstance(source, str) \
            or not isinstance(span, (list, tuple)) or len(span) != 2 \
            or any(type(x) is not int for x in span) or not 0 <= span[0] < span[1] <= len(source) \
            or source[span[0]:span[1]] != text:
        return False
    if not any(c.isspace() for c in text):
        return bool(atom_ok(text))
    if ref is None or text != text.strip():
        return False
    fold = (lambda s: s.casefold()) if ref["ignore_case"] else (lambda s: s)
    toks = [m.group() for m in re.finditer(r"\S+", text)]
    if len(toks) < 2:
        return False
    prefix = toks[0]
    for tail in ref["tails"]:
        parts = tail.split()
        if len(toks) != 1 + len(parts) or any(fold(x) != fold(y) for x, y in zip(toks[1:], parts)):
            continue
        for suf in ref["suffixes"]:
            if suf and not (len(prefix) > len(suf) and fold(prefix).endswith(fold(suf))):
                continue
            owner = prefix[:len(prefix) - len(suf)]
            if owner and ref["name"].fullmatch(owner) \
                    and atom_ok(owner) and not blocked(owner) and not any(blocked(w) for w in parts):
                return True
    return False


def _compound_word_blocked(parser, word, suffixes, head_ok, fold):
    """Shared D/P2 compound protection: negation/scope words or a fitted inner role marker (pure)."""
    if parser._protected_kind(word) in ("negation", "scope"):
        return True
    for s in suffixes:
        if s and len(word) > len(s) and fold(word).endswith(fold(s)):
            stem = word[:-len(s)]
            if head_ok(stem) and parser._particle_form(stem, s) == s:
                return True
    return False


def _bind_seed_roles(parser, source, declaration, frame, *, overlapping_alternatives=False):
    """Bind one selected two-role seed frame onto original source spans (pure)."""
    import hashlib
    import itertools
    import json
    import re

    def bad(msg):
        raise ValueError("seed role binder: " + msg)

    def strs(v, limit, name):
        if not isinstance(v, list) or len(v) > limit or any(not isinstance(x, str) for x in v) \
                or len(set(v)) != len(v):
            bad(name)
        return v

    if not isinstance(source, str):
        bad("source")
    if not isinstance(declaration, dict) or not isinstance(frame, dict):
        bad("declaration")
    keys = {"schema", "seed_count", "seed_sha256", "head_pattern", "separators", "terminators",
            "operators", "frames"}
    if set(declaration) - {"reference_forms"} != keys or declaration["schema"] != "predicate-frames-v2":
        bad("declaration keys")
    data = getattr(parser, "data", None) or {}
    ref = None
    if "reference_forms" in declaration:
        actual = data.get("predicate_frames") if isinstance(data, dict) else None
        if not isinstance(actual, dict) or actual.get("reference_forms") != declaration["reference_forms"]:
            bad("reference_forms")
        ref = _selected_reference_forms(parser)
        if ref is None:
            bad("reference_forms")
    fold = (lambda s: s.casefold()) if data.get("ignore_case") else (lambda s: s)
    flags = re.IGNORECASE if data.get("ignore_case") else 0
    pat = declaration["head_pattern"]
    if not isinstance(pat, str) or not pat.strip():
        bad("head_pattern")
    try:
        head = re.compile(pat, flags)
    except re.error:
        bad("head_pattern")
    if head.fullmatch(""):
        bad("head_pattern empty")
    seps, terms = strs(declaration["separators"], 16, "separators"), \
        strs(declaration["terminators"], 16, "terminators")
    if any(len(x) != 1 or x.isspace() or x.isalnum() for x in seps + terms) or set(seps) & set(terms):
        bad("punctuation")
    grammar = getattr(parser, "clause_grammar", None) or {}
    qmarks = [q for q in (grammar.get("question_marks") or grammar.get("question_mark") or [])
              ] if not isinstance(grammar.get("question_mark"), str) else [grammar["question_mark"]]
    if set(seps + terms) & set(qmarks):
        bad("punctuation conflicts with question mark")
    ops = strs(declaration["operators"], 16, "operators")
    if any(not o.strip() or o != o.strip() for o in ops):
        bad("operators")
    rows = declaration["frames"]
    if not isinstance(rows, list) or not rows or len(rows) > 16:
        bad("frames")
    ids = []
    endings = (getattr(parser, "inflection_grammar", None) or {}).get("endings", {})
    fkeys = {"id", "source_ref", "predicate_span", "roles", "allowed_endings"}
    rkeys = {"slot", "prefixes", "suffixes", "bare_side"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != fkeys or not isinstance(row["id"], str) \
                or not row["id"].strip():
            bad("frame row")
        ids.append(row["id"])
        allowed = strs(row["allowed_endings"], 64, "allowed_endings")
        if any(not a.strip() or a not in endings for a in allowed):
            bad("allowed_endings")
        if not isinstance(row["roles"], list) or len(row["roles"]) not in (2, 3):
            bad("roles")
        owners, bare = {}, set()
        for r in row["roles"]:
            if not isinstance(r, dict) or set(r) != rkeys or not isinstance(r["slot"], str) \
                    or not r["slot"].strip():
                bad("role")
            pre, suf = strs(r["prefixes"], 16, "prefixes"), strs(r["suffixes"], 16, "suffixes")
            if any(not p.strip() or p != p.strip() for p in pre) or any(not s or re.search(r"\s", s) for s in suf):
                bad("markers")
            side = r["bare_side"]
            if side not in (None, "before", "after") or [bool(pre), bool(suf), side is not None].count(True) != 1:
                bad("role mode")
            if side:
                if side in bare and len(row["roles"]) == 2:
                    bad("bare side")
                bare.add(side)
            for m in pre + suf:
                if owners.setdefault(m, r["slot"]) != r["slot"]:
                    bad("marker owner")
    if len(set(ids)) != len(ids):
        bad("frame ids")
    matches = [i for i, row in enumerate(rows) if row == frame]
    if len(matches) != 1:
        bad("target frame")
    compiled = [_compile_seed_predicate(parser, declaration, row) for row in rows]
    # Three-slot rows: one scalar slot (the triple's object) and two reference slots; the bare
    # sides may be shared only by one scalar and one reference role, and only on the after side.
    for row, comp in zip(rows, compiled):
        if len(comp["annotation"]["slots"]) == 3 and len(row["roles"]) == 3:
            scalar_name = comp["annotation"]["meaning"]["triple"][2][1:]
            sided = [(r["bare_side"], r["slot"] == scalar_name) for r in row["roles"] if r["bare_side"]]
            if sum(1 for s, _n in sided if s == "before") > 1:
                bad("bare side")
            after = [n for s, n in sided if s == "after"]
            if len(after) > 2 or (len(after) == 2 and sorted(after) != [False, True]):
                bad("bare side")
    target = compiled[matches[0]]
    annotation = target["annotation"]
    slot_count = len(annotation["slots"])
    if len(frame["roles"]) != slot_count or {r["slot"] for r in frame["roles"]} != set(annotation["slots"]) \
            or len({r["slot"] for r in frame["roles"]}) != slot_count:
        bad("slots")
    three = len(annotation["slots"]) == 3
    scalar_slot = annotation["meaning"]["triple"][2][1:] if three else None
    numerals = data.get("numerals") if isinstance(data, dict) else None
    numerals = numerals if isinstance(numerals, dict) else {}
    if not source.strip():
        return ("hold", "source_limit")
    words_all = [(m.start(), m.end()) for m in re.finditer(r"\S+", source)]
    if len(source) > _MAX_SOURCE or len(words_all) > _MAX_TOKENS:
        return ("hold", "source_limit")

    def form_of(f):
        if isinstance(f, dict):
            return f.get("text") or f.get("form"), f.get("inflection")
        return (f, None) if isinstance(f, str) else (f[0], f[1] if len(f) > 1 else None)

    def occurrences(forms):
        found = set()
        for f in forms:
            text, infl = form_of(f)
            for m in re.finditer(r"(?<!\w)" + re.escape(text) + r"(?!\w)", source, flags):
                found.add((m.start(), m.end(), fold(m.group()), None if infl is None else repr(sorted(infl.items()))))
        return found

    mine = occurrences(target["forms"])
    spans = {(a, b) for a, b, _t, _i in mine}
    if not mine:
        return ("hold", "missing_predicate")
    if len(mine) > 1:
        return ("hold", "ambiguous_predicate")
    ps, pe, ptext, _ = next(iter(mine))
    infl = next((form_of(f)[1] for f in target["forms"] if form_of(f)[0] and fold(form_of(f)[0]) == ptext), None)
    for k, c in enumerate(compiled):
        if k != matches[0]:
            if not overlapping_alternatives and any(not (b <= ps or a >= pe) for a, b, _t, _i in occurrences(c["forms"])):
                return ("hold", "ambiguous_predicate")
            if any(a >= pe or b <= ps for a, b, _t, _i in occurrences(c["forms"])):
                return ("hold", "ambiguous_predicate")
    if any(q and q in source[:ps] + "\0" + source[pe:] for q in qmarks):
        return ("hold", "unsupported_question")
    ending = (infl or annotation.get("inflection") or {}).get("ending") if isinstance(
        infl or annotation.get("inflection"), dict) else None
    if ending in (getattr(parser, "condition_endings", None) or grammar.get("condition_endings") or []):
        return ("hold", "unsupported_scope")
    if infl is not None and infl.get("ending") not in frame["allowed_endings"]:
        return ("hold", "unsupported_scope")

    # words outside the predicate, with declared punctuation split off
    punct, words = [], []
    pset = set(seps + terms)
    for a, b in ((0, ps), (pe, len(source))):
        for m in re.finditer(r"\S+", source[a:b]):
            s0, cur = a + m.start(), None
            for i, ch in enumerate(m.group()):
                if ch in pset:
                    cur = None
                    punct.append((s0 + i, s0 + i + 1, ch))
                elif cur is None:
                    cur = [s0 + i, s0 + i + 1]
                    words.append(cur)
                else:
                    cur[1] += 1
    words = [(a, b, source[a:b]) for a, b in words]
    tail = len(source.rstrip())
    for a, _b, ch in punct:
        if ch in terms and (a != tail - 1 or sum(1 for p in punct if p[2] in terms) > 1):
            return ("hold", "unconsumed_source")
    protected = set()
    for c in compiled:
        for f in c["forms"]:
            protected.update(fold(w) for w in form_of(f)[0].split())
    for r in (x for row in rows for x in row["roles"]):
        protected.update(fold(w) for m in r["prefixes"] + r["suffixes"] for w in m.split())
    opwords = {fold(w) for o in ops for w in o.split()}
    protected |= opwords
    for o in ops:
        for m in re.finditer(r"(?<!\w)" + re.escape(o) + r"(?!\w)", source[:ps] + "\0" + source[pe:], flags):
            return ("hold", "unsupported_scope")
    for _a, _b, w in words:
        if fold(w) in opwords or parser._protected_kind(w) in ("negation", "scope"):
            return ("hold", "unsupported_scope")

    def head_ok(t):
        return (
            bool(head.fullmatch(t))
            and fold(t) not in protected
            and parser._protected_kind(t) not in ("negation", "scope")
        )

    maxw = 1 + max(len(t.split()) for t in ref["tails"]) if ref is not None else 1
    all_suffixes = [s for row in rows for x in row["roles"] for s in x["suffixes"]]

    def blocked(w):
        return fold(w) in protected or _compound_word_blocked(parser, w, all_suffixes, head_ok, fold)

    def span_ok(a, b):
        if a >= b or (a < pe and b > ps):
            return False
        return _reference_span_ok(ref, source[a:b], head_ok, blocked, source, [a, b])

    scalar_pattern = None
    if three:
        from marco.language.numerals import parse_numeral
        # The lexical numeral route is available only when every declared table is a dict mapping
        # nonempty words to strict integers (empty tables are valid, as in parse_numeral);
        # otherwise plain decimal digits remain the sole scalar surface.
        vocab_ok = bool(numerals) and all(
            isinstance(t, dict) and all(isinstance(w, str) and w and isinstance(v, int)
                                        and not isinstance(v, bool) for w, v in t.items())
            for t in numerals.values())
        if not vocab_ok:
            numerals = {}
        numeral_words = sorted({w for t in numerals.values() for w in t}, key=len, reverse=True)
        unit = "(?:%s)" % "|".join(re.escape(w) for w in numeral_words) if numeral_words else ""
        scalar_pattern = re.compile((r"(?>\d+|%s+(?:[\s-]+%s+)*)" % (unit, unit)) if numeral_words
                                    else r"\d+", flags)

    def scalar_value(a, b):
        """Normalized decimal of one original source word's numeral surface, else None."""
        surface = source[a:b]
        if not surface or re.search(r"\s", surface) or (a < pe and b > ps):
            return None
        if not any(wa <= a and b <= wb for wa, wb in words_all):
            return None
        if not scalar_pattern.fullmatch(surface):
            return None
        try:
            value = parse_numeral(fold(surface), numerals)
        except (ValueError, TypeError, AttributeError):
            return None
        if type(value) is not str or not value or not value.isdecimal():
            return None
        return value

    def check(slot, a, b):
        if slot == scalar_slot:
            value = scalar_value(a, b)
            return value is not None, value
        return span_ok(a, b), None

    options = {}
    for r in frame["roles"]:
        opts = set()
        reach = len(words) if r["slot"] == scalar_slot else maxw
        for i, (a, b, w) in enumerate(words):
            for p in r["prefixes"]:
                parts = p.split()
                seq = words[i:i + len(parts)]
                if len(seq) == len(parts) and i + len(parts) < len(words) \
                        and all(fold(x[2]) == fold(y) for x, y in zip(seq, parts)):
                    hi = i + len(parts)
                    h = words[hi]
                    if source[seq[-1][1]:h[0]].strip() == "" and (len(parts) == 1 or all(
                            source[seq[j][1]:seq[j + 1][0]].strip() == "" for j in range(len(seq) - 1))):
                        for k in range(hi, min(len(words), hi + reach)):
                            good, norm = check(r["slot"], h[0], words[k][1])
                            if good:
                                opts.add(((h[0], words[k][1]), ((seq[0][0], seq[-1][1]),), "prefix",
                                          frozenset(range(i, k + 1)), source[seq[0][0]:seq[-1][1]], norm))
            for s in r["suffixes"]:
                if len(w) > len(s) and fold(w).endswith(fold(s)):
                    for j in range(max(0, i - reach + 1), i + 1):
                        good, norm = check(r["slot"], words[j][0], b - len(s))
                        if good and (
                                not any(c.isspace() for c in source[words[j][0]:b - len(s)])
                                or parser._particle_form(source[words[j][0]:b - len(s)], s) == s):
                            opts.add(((words[j][0], b - len(s)), ((b - len(s), b),), "suffix",
                                      frozenset(range(j, i + 1)), w[-len(s):], norm))
            if r["bare_side"]:
                for j in range(max(0, i - reach + 1), i + 1):
                    if ((b <= ps) if r["bare_side"] == "before" else (words[j][0] >= pe)):
                        good, norm = check(r["slot"], words[j][0], b)
                        if good:
                            opts.add(((words[j][0], b), (), None, frozenset(range(j, i + 1)), None, norm))
        options[r["slot"]] = sorted(opts, key=repr)
    if any(not o for o in options.values()):
        return ("hold", "unbound_roles")
    slots = [r["slot"] for r in frame["roles"]]
    done = {}
    if three:
        size = 1
        for s in slots:
            size *= len(options[s])
        if size > _MAX_ITEMS * _MAX_TOKENS:
            return ("hold", "candidate_limit")
        every = set(range(len(words)))
        for combo in itertools.product(*(options[s] for s in slots)):
            owned = [set(o[3]) for o in combo]
            union = set().union(*owned)
            if sum(len(x) for x in owned) != len(union) or union != every:
                continue
            done[tuple(o[:3] + (o[4],) for o in combo)] = combo
    else:
      for o1, o2 in itertools.product(options[slots[0]], options[slots[1]]):
        if o1[3] & o2[3] and not (o1[2] == "suffix" and o2[2] == "suffix" and o1[3] == o2[3] and False):
            continue
        if set(range(len(words))) != set(o1[3]) | set(o2[3]):
            continue
        done[(o1[:3] + (o1[4],), o2[:3] + (o2[4],))] = (o1, o2)
    if not done:
        return ("hold", "unconsumed_source")
    if len(done) > 1:
        return ("hold", "ambiguous_binding")
    chosen = dict(zip(slots, next(iter(done.values()))))
    roles_t = {s: {"value": source[o[0][0]:o[0][1]], "span": [o[0][0], o[0][1]]} for s, o in chosen.items()}
    markers = [{"slot": s, "kind": o[2], "text": source[m[0]:m[1]], "span": [m[0], m[1]]}
               for s, o in chosen.items() for m in o[1]]
    cover = sorted([list(o[0])] + [list(m) for m in o[1]] for o in chosen.values())
    coverage = sorted([c for grp in cover for c in grp] + [[ps, pe]] + [[a, b] for a, b, _c in punct])
    values = {s: v["value"] for s, v in roles_t.items()}
    if three:
        values[scalar_slot] = chosen[scalar_slot][5]
        roles_t[scalar_slot]["normalized"] = chosen[scalar_slot][5]
    meaning = substitute(deepcopy(annotation["meaning"]), values)
    trace = {"rule": "seed-constituents-v2", "source": source, "seed_count": target["seed_count"],
             "seed_sha256": target["seed_sha256"], "source_ref": deepcopy(target["source_ref"]),
             "frame_id": frame["id"],
             "declaration_sha256": hashlib.sha256(json.dumps(declaration, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest(),
             "predicate_span": [ps, pe], "roles": roles_t,
             "markers": sorted(markers, key=lambda m: m["span"]),
             "punctuation": [{"kind": "terminator" if ch in terms else "separator", "text": ch, "span": [a, b]}
                             for a, b, ch in punct],
             "coverage": coverage, "inflection": deepcopy(infl), "operators": [],
             "scope": [0, len(source)]}
    return ("ok", meaning, trace)

def _normalized_frame_authority(parser, record, compiled_frames, predicate_hits):
    """Pure association of one normalized template record with one selected frame (or None)."""
    import hashlib
    import itertools
    import json
    import re

    def canon(v):
        return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def sint(v):
        return isinstance(v, int) and not isinstance(v, bool)

    def flat(ann):
        """(slot -> span, triple) for a flat binary two-slot annotation, else None."""
        text, slots, meaning = ann.get("text"), ann.get("slots"), ann.get("meaning")
        if not isinstance(text, str) or not isinstance(slots, dict) or len(slots) != 2:
            return None
        spans = {}
        for name, value in slots.items():
            if not isinstance(name, str) or not name or not isinstance(value, str) or not value:
                return None
            found = [i for i in range(len(text)) if text.startswith(value, i)]
            if len(found) != 1:
                return None
            spans[name] = (found[0], found[0] + len(value))
        (a0, a1), (b0, b1) = sorted(spans.values())
        if a1 > b0 or len(set(slots.values())) != 2:
            return None
        if not isinstance(meaning, dict) or "triple" not in meaning \
                or not set(meaning) <= {"triple", "polarity", "modality"}:
            return None
        triple = meaning["triple"]
        if not isinstance(triple, list) or len(triple) != 3 \
                or not all(isinstance(t, str) and t for t in triple):
            return None
        refs = {"$" + n for n in slots}
        if triple[0] == triple[2] or triple[0] not in refs or triple[2] not in refs \
                or triple[1].startswith("$"):
            return None
        if "polarity" in meaning and not isinstance(meaning["polarity"], bool):
            return None
        if "modality" in meaning and meaning["modality"] not in ("asserted", "planned", "conditional"):
            return None
        return spans, triple

    def remap(value, names):
        if isinstance(value, str):
            return names.get(value, value)
        if isinstance(value, list):
            return [remap(v, names) for v in value]
        if isinstance(value, dict):
            return {k: remap(v, names) for k, v in value.items()}
        return value

    def negative_authority(norm, idx, digest, pairs, data):
        """declared-negation-v1 authority only via the pure bidirectional source verifier.

        Runs outside the positive broad catch: malformed data -> None; verifier errors propagate.
        """
        if not isinstance(norm, dict) or set(norm) != {"id", "canonical", "example_index", "polarity"} \
                or norm["polarity"] is not False or not isinstance(norm["canonical"], str) \
                or norm["canonical"] != record.get("canonical") or not isinstance(record.get("source"), str) \
                or not isinstance(data, dict):
            return None
        caps = data.get("semantic_capabilities")
        cap = caps.get("negative_binary") if isinstance(caps, dict) else None
        if not isinstance(cap, dict) or cap.get("schema") != "selected-negative-binary-v1" \
                or not isinstance(cap.get("basis"), dict) or not isinstance(cap.get("capability_sha256"), str) \
                or not isinstance(cap["basis"].get("frame_refs"), list):
            return None
        try:
            if hashlib.sha256(canon(cap["basis"]).encode("utf-8")).hexdigest() != cap["capability_sha256"]:
                return None
            members = {canon(r) for r in cap["basis"]["frame_refs"]}
        except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
            return None
        verify = getattr(parser, "verify_selected_binary_witness", None)
        if not callable(verify):
            return None
        got = verify(record["source"], record, "negative_fact")
        if not isinstance(got, dict) or set(got) != {"source_ref", "compiler_index", "meaning", "capability_sha256"}:
            return None
        ref, meaning = got["source_ref"], got["meaning"]
        if got["capability_sha256"] != cap["capability_sha256"] or not sint(got["compiler_index"]) \
                or got["compiler_index"] != idx or not isinstance(ref, dict) or not sint(ref.get("index")) \
                or ref["index"] != idx or ref.get("annotation_sha256") != digest \
                or not isinstance(meaning, dict) or meaning.get("polarity") is not False:
            return None
        try:
            full = canon(ref)
            compact = canon({"index": ref["index"], "annotation_sha256": digest,
                             "source_ref_sha256": hashlib.sha256(full.encode("utf-8")).hexdigest()})
            found = [(row, comp) for row, comp in pairs
                     if isinstance(row, dict) and isinstance(comp, dict)
                     and isinstance(comp.get("source_ref"), dict) and canon(comp["source_ref"]) == full]
        except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
            return None
        if compact not in members or len(found) != 1 or "id" not in found[0][0]:
            return None
        row, comp = found[0]
        want = {k: v for k, v in norm.items() if k != "example_index"}
        return {"frame_id": row["id"], "seed_source_ref": deepcopy(comp["source_ref"]),
                "active_index": idx, "active_annotation_sha256": digest, "inflection": deepcopy(want)}

    def run():
        data = getattr(parser, "data", None)
        if not isinstance(data, dict) or not isinstance(record, dict) or len(record) != 11:
            return None
        decl = data.get("predicate_frames")
        if not isinstance(decl, dict) or not isinstance(decl.get("frames"), list):
            return None
        count = decl.get("seed_count")
        flags = re.IGNORECASE if data.get("ignore_case") else 0
        fold = (lambda s: s.casefold()) if flags else (lambda s: s)
        if not isinstance(compiled_frames, list) or not isinstance(predicate_hits, list):
            return None
        pairs = []
        for item in compiled_frames:
            if not isinstance(item, tuple) or len(item) != 2:
                return None
            row, comp = item
            if sum(1 for r in decl["frames"] if r == row) != 1:
                return None
            if comp != _compile_seed_predicate(parser, decl, row):
                return None
            pairs.append((row, comp))
        source, idx, norm = record.get("source"), record.get("example_index"), record.get("normalization")
        examples = data.get("examples")
        if not isinstance(source, str) or not sint(idx) or not isinstance(examples, list) \
                or not 0 <= idx < len(examples) or not isinstance(norm, dict) \
                or norm.get("example_index") != idx:
            return None
        ann = examples[idx]
        digest = hashlib.sha256(canon(ann).encode("utf-8")).hexdigest()
        if record.get("annotation_sha256") != digest or record.get("reader_kind") != "template":
            return None
        want = {k: v for k, v in norm.items() if k != "example_index"}
        if norm.get("id") == "declared-negation-v1":
            return (_negative_deferred, (norm, idx, digest, pairs, data))
        hits = []
        for h in predicate_hits:
            if not isinstance(h, dict) or not isinstance(h.get("frame_id"), str) \
                    or not isinstance(h.get("text"), str):
                return None
            hits.append(h)

        def linked(row, comp, fixed=None):
            if want.get("ending") not in row["allowed_endings"]:
                return False
            for f in comp["forms"]:
                infl = f.get("inflection")
                if isinstance(infl, (list, tuple)):
                    infl = dict(infl)
                if infl != want:
                    continue
                for h in hits:
                    if h["frame_id"] != row["id"] or fold(h["text"]) != fold(f["text"]):
                        continue
                    if fixed is None:
                        return True
                    span = h.get("span")
                    if isinstance(span, list) and len(span) == 2 and all(sint(v) for v in span) \
                            and source[span[0]:span[1]] == h["text"] \
                            and any(a <= span[0] and span[1] <= b for a, b in fixed):
                        return True
            return False

        found = []
        if sint(count) and idx < count:
            for row, comp in pairs:
                ref = comp["source_ref"]
                if ref.get("index") == idx and ref.get("annotation_sha256") == digest and linked(row, comp):
                    found.append((row, comp))
        else:
            fixed = active_proof(ann, idx, digest, want, source, flags, fold, decl)
            if fixed is None:
                return None
            for row, comp in pairs:
                if linked(row, comp, fixed) and role_map(row, comp, ann, fold) is not None:
                    found.append((row, comp))
        if not found or (not (sint(count) and idx < count) and len(found) != 1):
            return None
        row, comp = found[0]
        return {"frame_id": row["id"], "seed_source_ref": deepcopy(comp["source_ref"]),
                "active_index": idx, "active_annotation_sha256": digest, "inflection": deepcopy(want)}

    def active_proof(ann, idx, digest, want, source, flags, fold, decl):
        """Fixed spans of the record when every active-row proof passes, else None."""
        templates = getattr(parser, "templates", None)
        if not isinstance(templates, list) or idx >= len(templates):
            return None
        data = parser.data
        fresh = parser.compile(ann, data.get("numerals", {}), parser.slot_particles,
                               ignore_case=bool(data.get("ignore_case")),
                               counters=parser.counters, pointers=parser.pointers)
        actual = templates[idx]
        if not isinstance(fresh, (tuple, list)) or len(fresh) < 2 or not isinstance(actual, (tuple, list)) \
                or len(actual) < 2:
            return None
        key = lambda ps: [(p.pattern, p.flags) for p in ps]
        if key(actual[0]) != key(fresh[0]) or actual[1] != fresh[1]:
            return None
        canonical = record.get("canonical")
        if not isinstance(canonical, str) or not any(p.fullmatch(canonical) for p in actual[0]):
            return None
        shape = flat(ann)
        if shape is None:
            return None
        caps, fixed = record.get("capture_spans"), record.get("fixed_spans")
        if not isinstance(caps, dict) or set(caps) != set(ann["slots"]) or not isinstance(fixed, list):
            return None
        spans = []
        for cap in caps.values():
            if not isinstance(cap, dict) or not isinstance(cap.get("span"), list) \
                    or len(cap["span"]) != 2 or not all(sint(v) for v in cap["span"]):
                return None
            lo, hi = cap["span"]
            if not 0 <= lo < hi <= len(source) or cap.get("value") != source[lo:hi]:
                return None
            spans.append((lo, hi))
        fixed_pairs = []
        for pair in fixed:
            if not isinstance(pair, list) or len(pair) != 2 or not all(sint(v) for v in pair) \
                    or not 0 <= pair[0] < pair[1] <= len(source):
                return None
            fixed_pairs.append((pair[0], pair[1]))
        cursor = 0
        for lo, hi in sorted(spans + fixed_pairs):
            if lo < cursor or source[cursor:lo].strip():
                return None
            cursor = hi
        if source[cursor:].strip():
            return None
        # exact inflected suffix realization of the typed source
        marks = set()
        grammar = getattr(parser, "clause_grammar", None) or {}
        for mark in (list(decl.get("terminators") or []) + list(grammar.get("question_marks") or [])
                     + [grammar.get("question_mark")]):
            if isinstance(mark, str) and len(mark) == 1 and not mark.isspace():
                marks.add(mark)
        literal = source.strip()
        if literal and literal[-1] in marks:
            literal = literal[:-1].strip()
        want = {k: v for k, v in record["normalization"].items() if k != "example_index"}
        for surface, suffix, trace in parser._inflected_examples(ann):
            if trace == want and isinstance(suffix, str) and suffix and isinstance(surface, str) \
                    and canonical.endswith(suffix) \
                    and fold(canonical[:-len(suffix)] + surface) == fold(literal):
                return fixed_pairs
        return None

    def role_map(row, comp, ann, fold):
        """Unique active slot -> selected raw slot mapping from lexical role declarations."""
        shape, raw = flat(ann), flat(comp["annotation"])
        if shape is None or raw is None:
            return None
        spans, triple = shape
        text, kernel = ann["text"], comp["canonical_predicate"]
        roles = {r["slot"]: r for r in row["roles"]}
        if set(roles) != set(comp["annotation"]["slots"]):
            return None
        places = [i for i in range(len(text)) if text.startswith(kernel, i)
                  and not any(i < hi and lo < i + len(kernel) for lo, hi in spans.values())]
        if len(places) != 1:
            return None
        k0, k1 = places[0], places[0] + len(kernel)

        def fits(name, role):
            lo, hi = spans[name]
            before, after = text[:lo].rstrip(), text[hi:]
            for p in role["prefixes"]:
                if fold(before[len(before) - len(p):]) == fold(p) and len(before) >= len(p) \
                        and (len(before) == len(p) or not re.match(r"\w", before[-len(p) - 1])):
                    return True
            for s in role["suffixes"]:
                if fold(after[:len(s)]) == fold(s) and not re.match(r"\w", after[len(s):len(s) + 1]):
                    return True
            side = role["bare_side"]
            return (side == "before" and hi <= k0) or (side == "after" and lo >= k1)

        names, good = list(spans), []
        for perm in itertools.permutations(roles):
            if all(fits(n, roles[r]) for n, r in zip(names, perm)):
                good.append(dict(zip(names, perm)))
        if len(good) != 1:
            return None
        mapped = remap(ann["meaning"], {"$" + a: "$" + r for a, r in good[0].items()})
        return good[0] if mapped == comp["annotation"]["meaning"] else None

    _negative_deferred = object()
    try:
        out = run()
    except Exception:
        return None
    if type(out) is tuple and len(out) == 2 and out[0] is _negative_deferred:
        return negative_authority(*out[1])
    return out


def _select_unique_seed_flat(parser, source, declaration):
    """Unique flat meaning over every declared seed frame (pure; overlapping alternatives)."""
    import json
    from copy import deepcopy

    def canon(v):
        return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    if not isinstance(source, str):
        raise ValueError("seed role binder: source")
    if not isinstance(declaration, dict):
        raise ValueError("seed role binder: declaration")
    rows = declaration.get("frames")
    if not isinstance(rows, list) or not rows or len(rows) > 16:
        raise ValueError("seed role binder: frames")
    oks, reason = [], None
    for row in rows:
        out = _bind_seed_roles(parser, source, declaration, row, overlapping_alternatives=True)
        if out and out[0] == "ok":
            oks.append({"meaning": deepcopy(out[1]), "trace": deepcopy(out[2])})
        elif out and out[0] == "hold":
            reason = reason or out[1]
    if len({canon(c["meaning"]) for c in oks}) == 1:
        return ("ok", deepcopy(oks[0]["meaning"]), deepcopy(oks[0]["trace"]))
    return ("hold", "ambiguous_binding" if oks else (reason or "no_binding"))


def _declared_route(parser, source, *, phase, legacy_witnesses=(), literal=None, guard_names=True,
                    exclude=(), legacy_selection=None):
    """Pure route over a predicate-frames-v2 declaration (no activation, no writes)."""
    import hashlib
    import json
    import re
    from copy import deepcopy

    def bad(msg):
        raise ValueError("declared route: " + msg)

    def canon(v):
        return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    if not isinstance(source, str):
        bad("source")
    if phase not in ("whole", "clause"):
        bad("phase")
    if not isinstance(legacy_witnesses, (list, tuple)):
        bad("legacy_witnesses")
    if legacy_selection is not None and not isinstance(legacy_selection, dict):
        bad("legacy_selection")
    if literal is not None and not isinstance(literal, str):
        bad("literal")
    if legacy_selection is not None:
        legacy_selection.clear()
    data = getattr(parser, "data", None) or {}
    decl = data.get("predicate_frames")
    if decl is None:
        return None
    if not isinstance(decl, dict):
        bad("declaration")
    if decl.get("schema") == "predicate-frames-v1":
        return None
    if decl.get("schema") != "predicate-frames-v2":
        bad("schema")
    rows = decl.get("frames")
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        bad("frames")
    _bind_seed_roles(parser, "", decl, rows[0])
    compiled = [_compile_seed_predicate(parser, decl, row) for row in rows]
    flags = re.IGNORECASE if data.get("ignore_case") else 0
    hits = []
    for row, comp in zip(rows, compiled):
        texts = sorted({f["text"] for f in comp["forms"]}, key=lambda t: (-len(t), t))
        for text in texts:
            for m in re.finditer(r"(?<!\w)" + re.escape(text) + r"(?!\w)", source, flags):
                hits.append({"frame_id": row["id"], "source_ref": deepcopy(comp["source_ref"]),
                             "span": [m.start(), m.end()], "text": source[m.start():m.end()]})
    hits.sort(key=lambda h: (h["span"], h["frame_id"]))

    def result(kind, flat=(), keys=(), reason=None):
        return {"schema": "declared-route-v2", "version": 2, "kind": kind, "source": source,
                "predicate_hits": hits, "flat_candidates": [dict(c) for c in flat],
                "legacy_keys": list(keys), "reason": reason}

    if not hits and not legacy_witnesses:
        return result("none")

    grammar = getattr(parser, "clause_grammar", None) or {}
    marks = set()
    for mark in (list(decl.get("terminators") or []) + list(grammar.get("question_marks") or [])
                 + [grammar.get("question_mark")]):
        if isinstance(mark, str) and len(mark) == 1 and not mark.isspace():
            marks.add(mark)
    qmarks = set(m for m in (list(grammar.get("question_marks") or []) + [grammar.get("question_mark")])
                 if isinstance(m, str))
    if literal is None:
        literal = source.strip()
        if literal and literal[-1] in marks:
            literal = literal[:-1]
    records = {}
    sel_derivations, sel_matched = {}, {}
    best = parser._legacy_clause_meanings(literal, derivations=sel_derivations, matched=sel_matched,
                                          guard_names=guard_names, exclude=exclude, source=source,
                                          records=records)
    if legacy_selection is not None:
        legacy_selection.update({"literal": literal, "source": source, "meanings": deepcopy(best),
                                 "derivations": deepcopy(sel_derivations),
                                 "matched": deepcopy(sel_matched), "records": deepcopy(records)})
    best_keys = [k for k in (best or []) if k in records] if not isinstance(best, dict) \
        else [k for k in best if k in records]
    fresh = {canon(r) for k, r in records.items() if k in best_keys}
    for req in legacy_witnesses:
        if not isinstance(req, dict) or canon(req) not in fresh:
            bad("witness")
    if not hits:
        return result("none")

    heads_re = re.compile(decl["head_pattern"], flags)
    reserved = set()
    for row, comp in zip(rows, compiled):
        for f in comp["forms"]:
            reserved.update(f["text"].split())
        for r in row["roles"]:
            for phrase in r["prefixes"] + r["suffixes"]:
                reserved.add(phrase)
                reserved.update(phrase.split())
    for phrase in decl.get("operators") or []:
        reserved.add(phrase)
        reserved.update(phrase.split())
    folded = {x.casefold() if flags else x for x in reserved}
    has_q = bool(source.strip()) and source.strip()[-1] in qmarks
    kernel_marks = [h["span"] for h in hits]

    def refs(term, out):
        if isinstance(term, str):
            if term.startswith("$"):
                out.add(term[1:])
            return True
        if isinstance(term, list):
            return all(refs(t, out) for t in term)
        return False

    def entities(node, out):
        ok = True
        if isinstance(node, dict):
            tri = node.get("triple")
            if tri is not None:
                if not isinstance(tri, list) or len(tri) != 3:
                    return False
                ok = refs(tri[0], out) and refs(tri[2], out)
            for k, v in node.items():
                if k != "triple":
                    ok = entities(v, out) and ok
        elif isinstance(node, list):
            for v in node:
                ok = entities(v, out) and ok
        return ok

    def eligible(rec):
        if not isinstance(rec, dict) or len(rec) != 11 or rec.get("source") != source:
            return False
        idx = rec.get("example_index")
        exs = data.get("examples") or []
        if type(idx) is not int or not 0 <= idx < len(exs):
            return False
        example = exs[idx]
        if rec.get("annotation_sha256") != hashlib.sha256(canon(example).encode("utf-8")).hexdigest():
            return False
        caps, fixed, kind = rec.get("capture_spans"), rec.get("fixed_spans"), rec.get("reader_kind")
        if not isinstance(caps, dict) or not isinstance(fixed, list):
            return False
        if kind == "guard" and not (isinstance(rec.get("grammar_scope"), dict)
                                    and rec["grammar_scope"].get("kind") == "guard"):
            return False
        if kind not in ("template", "guard", "query", "definition", "invoke"):
            return False
        if has_q and kind == "template":
            return False
        norm = rec.get("normalization")
        if kind == "template" and norm is not None:
            if not isinstance(norm, dict) or norm.get("example_index") != idx:
                return False
            if _normalized_frame_authority(parser, rec, list(zip(rows, compiled)), hits) is None:
                return False
        meaning = example.get("meaning")
        define = meaning.get("define") if isinstance(meaning, dict) else None
        body = None
        if isinstance(define, dict) and isinstance(define.get("몸통"), str) \
                and define["몸통"].startswith("$"):
            body = define["몸통"][1:]
        names = set()
        if not entities(meaning, names):
            return False
        slots = example.get("slots") or {}
        for name in names:
            cap = caps.get(name)
            if name == body or cap is None:
                if cap is None and name != body:
                    return False
                continue
            if isinstance(slots.get(name), str) and slots[name].isdecimal():
                continue
            head = cap["value"]

            def atom_ok(t):
                if not heads_re.fullmatch(t):
                    return False
                pk = str(parser._protected_kind(t) or "")
                if pk and not ("numeral" in pk or "counter" in pk):
                    return False
                return not any((w.casefold() if flags else w) in folded for w in t.split())

            all_suffixes = [s for row in rows for x in row["roles"] for s in x["suffixes"]]

            def word_blocked(w):
                return (w.casefold() if flags else w) in folded \
                    or _compound_word_blocked(parser, w, all_suffixes, atom_ok,
                                              (lambda t: t.casefold()) if flags else (lambda t: t))

            if not isinstance(head, str) or not _reference_span_ok(
                    _selected_reference_forms(parser), head, atom_ok, word_blocked, source, cap.get("span")):
                return False
        for lo, hi in kernel_marks:
            if any(a <= lo and hi <= b for a, b in fixed):
                continue
            if body in caps and caps[body]["span"][0] <= lo and hi <= caps[body]["span"][1] \
                    and body is not None:
                continue
            return False
        return True

    owned = [k for k in best_keys if eligible(records[k])]
    if owned:
        return result("legacy", keys=owned)

    sel = _select_unique_seed_flat(parser, source, decl)
    if sel[0] == "ok":
        return result("flat", flat=[{"meaning": sel[1], "trace": sel[2]}])
    return result("segment" if phase == "whole" else "blocked", reason=sel[1])


def _check_declaration(decl):
    """Validate ``predicate_frames`` (schema predicate-frames-v1); ValueError when malformed."""
    import re

    def need(ok, what):
        if not ok:
            raise ValueError("predicate_frames: invalid " + what)

    def word(value):
        return isinstance(value, str) and bool(value) and not any(c.isspace() for c in value)

    def listed(key, row=None):
        value = (row if row is not None else decl).get(key, [])
        need(isinstance(value, list) and len(value) <= _MAX_ITEMS, key)
        return value

    need(isinstance(decl, dict) and decl.get("schema") == "predicate-frames-v1", "schema")
    need(set(decl) <= {"schema", "head_pattern", "modifiers", "terminators", "operators", "frames"}, "keys")
    try:
        head = re.compile(decl["head_pattern"])
    except (KeyError, TypeError, re.error):
        raise ValueError("predicate_frames: invalid head_pattern")
    modifiers, terminators = listed("modifiers"), listed("terminators")
    need(all(word(m) for m in modifiers) and all(word(t) for t in terminators), "modifiers/terminators")
    operators, forms, markers = {}, {}, set()
    for row in listed("operators"):
        need(isinstance(row, dict) and set(row) <= {"id", "form", "metadata"}
             and isinstance(row.get("id"), str) and row["id"] and word(row.get("form"))
             and row["form"] not in operators, "operator")
        meta = row.get("metadata")
        need(isinstance(meta, dict) and meta and set(meta) <= {"polarity", "modality"}
             and ("polarity" not in meta or isinstance(meta["polarity"], bool))
             and ("modality" not in meta or meta["modality"] in ("asserted", "planned", "conditional")),
             "operator metadata")
        operators[row["form"]] = row
    need(len({r["id"] for r in operators.values()}) == len(operators), "operator ids")
    frames = listed("frames")
    need(frames and all(isinstance(f, dict) and isinstance(f.get("id"), str) and f["id"] for f in frames)
         and len({f["id"] for f in frames}) == len(frames), "frames")
    for frame in frames:
        need(isinstance(frame, dict) and isinstance(frame.get("id"), str) and frame["id"]
             and set(frame) <= {"id", "forms", "roles", "meaning"}
             and isinstance(frame.get("meaning"), dict), "frame")
        meaning = frame["meaning"]
        need(set(meaning) <= {"triple", "polarity", "modality"}
             and isinstance(meaning.get("triple"), list) and len(meaning["triple"]) == 3
             and all(isinstance(t, str) and t.strip() and t != "$" for t in meaning["triple"])
             and ("polarity" not in meaning or isinstance(meaning["polarity"], bool))
             and ("modality" not in meaning or meaning["modality"] in ("asserted", "planned", "conditional")),
             "meaning")
        roles = listed("roles", frame)
        need(listed("forms", frame), "forms")
        frame_markers = set()
        names = [r.get("name") for r in roles if isinstance(r, dict)]
        need(roles and len(names) == len(roles) and all(isinstance(n, str) and n for n in names)
             and len(set(names)) == len(names), "roles")
        sides = []
        for role in roles:
            need(set(role) <= {"name", "marker", "side"} and role.get("side") in ("before", "after")
                 and ("marker" not in role or (word(role["marker"]) and role["marker"] not in frame_markers)),
                 "role")
            if "marker" in role:
                frame_markers.add(role["marker"])
                markers.add(role["marker"])
            else:
                sides.append(role["side"])
        need(len(set(sides)) == len(sides), "unmarked role sides")

        def refs(value):
            if isinstance(value, str):
                return {value[1:]} if value.startswith("$") else set()
            items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
            return set().union(*(refs(v) for v in items)) if items else set()
        need(refs(frame["meaning"]) <= set(names), "meaning references")
        for form in listed("forms", frame):
            need(word(form) and form not in forms and form not in operators, "form")
            forms[form] = frame
    need(not markers & (set(forms) | set(operators) | set(modifiers)), "marker collision")
    return head, set(modifiers), terminators, operators, forms


def declared_source(parser, text, evidence):
    """The clause as typed, with its declared terminal punctuation (clause_spans drops it)."""
    decl = parser.data.get("predicate_frames")
    if decl is None:
        return evidence["text"]
    tail = text[evidence["end"]:]
    if isinstance(decl, dict) and decl.get("schema") == "predicate-frames-v2":
        # v2: the original evidence plus at most one selected terminator or question mark; no host fallback.
        selected = [*(decl.get("terminators") or []), *parser.clause_grammar.get("question_marks", [])]
        for mark in sorted(selected, key=lambda m: len(m) if isinstance(m, str) else 0, reverse=True):
            if isinstance(mark, str) and mark and tail.startswith(mark):
                return text[evidence["start"]:evidence["end"] + len(mark)]
        return text[evidence["start"]:evidence["end"]]
    for mark in sorted((decl.get("terminators") or []) if isinstance(decl, dict) else [], key=len, reverse=True):
        if isinstance(mark, str) and mark and tail.startswith(mark):
            return text[evidence["start"]:evidence["end"] + len(mark)]
    return evidence["text"]


def _registered_query(parser, asked, head, modifiers, reserved):
    """Does an existing compiled query template fullmatch ``asked`` (source minus its suffix only)?
    "valid": every captured slot is modifiers + one head word, none of them a declared predicate,
    marker or operator word. "malformed": a template matches but a slot swallowed unread text.
    None: no registered query template matches. Single clause only; no word rewriting."""
    templates = getattr(parser, "templates", None) or []
    examples = (getattr(parser, "data", None) or {}).get("examples") or []
    matched = False
    for (patterns, meaning), _example in zip(templates, examples):
        if not isinstance(meaning, dict) or "query" not in meaning:
            continue
        for pattern in patterns:
            match = pattern.fullmatch(asked)
            if match is None:
                continue
            matched = True
            ok = True
            for value in match.groupdict().values():
                words = (value or "").split()
                if not words:
                    ok = False
                    break
                *front, last = words
                if (last in reserved or not head.fullmatch(last)
                        or any(w in reserved or w not in modifiers for w in front)):
                    ok = False
                    break
            if ok:
                return "valid"
    return "malformed" if matched else None


def declared_clause(parser, source):
    """Opt-in single-clause constituent reader. None: no declaration or no declared predicate in
    ``source``. ("hold", reason): the declaration owns the clause but cannot read it all.
    ("ok", meaning, trace): a reading whose coverage is every non-space character."""
    import hashlib
    import json
    import re
    decl = parser.data.get("predicate_frames")
    if decl is None:
        return None
    head, modifiers, terminators, operators, forms = _check_declaration(decl)
    hits = [m for form in forms for m in re.finditer(r"(?<!\w)%s(?!\w)" % re.escape(form), source)]
    if not hits:
        return None
    if len(hits) > 1 or len(source) > _MAX_SOURCE:
        return ("hold", "multiple predicates" if len(hits) > 1 else "source too long")
    body, terminal = source.rstrip(), None
    # A registered query template using this predicate keeps its own (query) meaning: the
    # constituent frame never reads a question as an asserted fact. The source is matched
    # as typed minus only its selected question mark or declared terminal suffix.
    reserved = set(forms) | set(operators) | {r["marker"] for f in forms.values() for r in f["roles"] if "marker" in r}
    question_marks = [m for m in (getattr(parser, "clause_grammar", None) or {}).get("question_marks", [])
                      if isinstance(m, str) and m]
    asked_mark = next((m for m in sorted(question_marks, key=len, reverse=True) if body.endswith(m)), None)
    asked = body[:len(body) - len(asked_mark)].rstrip() if asked_mark else None
    if asked is None:
        for mark in sorted(terminators, key=len, reverse=True):
            if body.endswith(mark):
                asked = body[:len(body) - len(mark)].rstrip()
                break
    registered = _registered_query(parser, asked if asked is not None else body, head, modifiers, reserved)
    if registered == "valid":
        return None                                     # legacy query reading, unchanged
    if registered == "malformed":
        return ("hold", "query slot would swallow unread text")
    if asked_mark is not None:
        return ("hold", "question-marked source is not a registered query")
    for mark in sorted(terminators, key=len, reverse=True):
        if body.endswith(mark):
            terminal, body = [len(body) - len(mark), len(body)], body[:len(body) - len(mark)]
            break
    tokens = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", body)]
    if len(tokens) > _MAX_TOKENS:
        return ("hold", "too many tokens")
    meta, used, applied, at = {}, set(), [], 0
    while at < len(tokens) and tokens[at][2] in operators:
        row = operators[tokens[at][2]]
        if row["id"] in used or any(k in meta and meta[k] != v for k, v in row["metadata"].items()):
            return ("hold", "conflicting operator")
        used.add(row["id"])
        meta.update(row["metadata"])
        applied.append({"id": row["id"], "span": [tokens[at][0], tokens[at][1]], "scope": [0, len(source)]})
        at += 1
    rest = tokens[at:]
    where = [k for k, t in enumerate(rest) if t[2] in forms]
    if len(where) != 1:
        return ("hold", "predicate is not a clause word")
    frame, predicate = forms[rest[where[0]][2]], rest[where[0]]
    by_marker = {r["marker"]: r for r in frame["roles"] if "marker" in r}
    bare = {}
    for r in frame["roles"]:                            # a marker does not remove the default position
        bare.setdefault(r["side"], []).append(r)
    groups = []                                         # [role, constituent tokens, marker token]
    for side, segment in (("before", rest[:where[0]]), ("after", rest[where[0] + 1:])):
        current = None
        for token in segment:
            if token[2] in by_marker:
                if current is not None and not current[1]:
                    return ("hold", "marker without value")
                current = [by_marker[token[2]], [], token]
                groups.append(current)
            else:
                if current is None:
                    if len(bare.get(side, [])) != 1:
                        return ("hold", "unmarked text" if side not in bare else "ambiguous unmarked text")
                    current = [bare[side][0], [], None]
                    groups.append(current)
                current[1].append(token)
        if current is not None and not current[1]:
            return ("hold", "marker without value")
    roles, mods = {}, []
    for role, words, _marker in groups:
        *front, last = words
        # The same declaration-derived boundary the query guard uses: no declared form,
        # operator or role marker may be read as a constituent head or retained modifier.
        if role["name"] in roles or last[2] in reserved or not head.fullmatch(last[2]) \
                or any(w[2] in reserved or w[2] not in modifiers for w in front):
            return ("hold", "extra role or unknown constituent word")
        mods += [{"span": [w[0], w[1]], "semantics": "retained_entity_reference"} for w in front]
        roles[role["name"]] = {"value": " ".join(w[2] for w in words), "span": [words[0][0], last[1]]}
    if set(roles) != {r["name"] for r in frame["roles"]}:
        return ("hold", "missing role")
    meaning = substitute(frame["meaning"], {k: v["value"] for k, v in roles.items()})
    if any(k in meaning for k in meta):
        return ("hold", "operator conflicts with meaning")
    meaning = {**meaning, **meta}
    covered = sorted([t[0], t[1]] for t in tokens) + ([terminal] if terminal else [])
    trace = {"rule": "declared-constituents-v1", "source": source,
             "declaration_sha256": hashlib.sha256(json.dumps(decl, sort_keys=True).encode()).hexdigest(),
             "frame_id": frame["id"], "predicate_span": [predicate[0], predicate[1]], "roles": roles,
             "modifiers": sorted(mods, key=lambda m: m["span"]), "operators": applied, "coverage": covered}
    return ("ok", meaning, trace)


def particle_key(particle, groups):
    """같은 자리를 채우는 조사는 한 이름으로 부른다. `로` 와 `으로` 는 한 자리다."""
    for group in groups:
        if particle in group:
            return group[0]
    return particle


def split_particle(word, particles, groups):
    """낱말을 (앞말, 자리) 로 가른다. 조사가 안 보이면 None."""
    for particle in particles:                      # 긴 조사를 먼저 본다
        if len(word) > len(particle) and word.endswith(particle):
            return word[:-len(particle)], particle_key(particle, groups)
    return None


def _marked(value, particles, groups):
    """이 값이 **조사를 넘어서 잘렸나.** 넘어섰으면 자름이 틀렸다.

    낱말 하나만 잡았다면 조사를 넘은 것이 아니다. 낱말 하나에 대고 조사를 떼
    보면 멀쩡한 이름을 버린다 — `사과` 의 `과`, `모과` 의 `과` 는 조사가 아니라
    이름의 끝 글자다. 조사는 앞말에 붙고 뒤는 띄우므로, **띄어쓰기를 넘어선
    자리에 조사가 보일 때만** 잘못 잘린 것이다.
    """
    words = value.split()
    return len(words) > 1 and any(split_particle(word, particles, groups) for word in words)


def _spans(example):
    text, slots = example["text"], example["slots"]
    return sorted((text.index(v), text.index(v) + len(v), k) for k, v in slots.items())


def _particle_at(text, end, particles, groups):
    """이 자리 바로 뒤에 붙은 조사. 조사가 아니면 None."""
    rest = text[end:]
    for particle in particles:
        if rest.startswith(particle) and not rest[len(particle):len(particle) + 1].strip():
            return particle_key(particle, groups)
    return None


def _chunks(example, particles, groups):
    """예문을 **조사가 끝맺는 덩이**로 나눈다. 덩이마다 그 안의 자리도 함께.

        하루가 | 모래에게 | 구슬 2개를 | 줬다
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^ 풀이말

    덩이를 알면 자리를 빼는 것도 자리 순서를 바꾸는 것도 같은 일이 된다.
    한국어는 조사가 자리를 짚으므로 덩이 순서는 뜻을 안 바꾼다.
    """
    text, spans = example["text"], _spans(example)
    tokens, cursor = [], 0
    for word in text.split():
        start = text.index(word, cursor)
        tokens.append((start, start + len(word)))
        cursor = start + len(word)
    chunks, current = [], []
    for start, end in tokens:
        current.append((start, end))
        if split_particle(text[start:end], particles, groups):
            chunks.append(current); current = []
    def inside(piece):
        low, high = piece[0][0], piece[-1][1]
        return {name: example["slots"][name] for s, e, name in spans if low <= s and e <= high}
    return ([(text[piece[0][0]:piece[-1][1]], inside(piece)) for piece in chunks],
            (text[current[0][0]:] if current else ""),
            (inside(current) if current else {}))


def _elisions(example, particles, groups, reorder=False):
    """자리를 빼고 순서를 바꾼 조각 사례들. 뺀 자리가 곧 사건이 채울 자리다.

    앞에서부터만 빼면 `구슬 2개를 상대에게 주는` 처럼 **순서만 다른** 말을 못
    읽는다. 반례마다 예문을 더하지 않고 덩이를 다시 늘어놓는다.
    """
    from itertools import combinations, permutations
    text = example["text"]
    chunks, tail, tail_slots = _chunks(example, particles, groups)
    if not chunks:
        return
    seen = set()
    for keep in range(len(chunks), -1, -1):
        arrangements = (permutations(range(len(chunks)), keep) if reorder else
                        combinations(range(len(chunks)), keep))
        for chosen in arrangements:
            order = sorted(chosen)
            dropped = {}
            for index, (_piece, slots) in enumerate(chunks):
                if index in chosen:
                    continue
                for name in slots:
                    end = text.index(example["slots"][name]) + len(example["slots"][name])
                    dropped[name] = _particle_at(text, end, particles, groups)
            if any(key is None for key in dropped.values()):
                continue            # 조사 없이 지워진 자리는 사건이 채울 길이 없다
            body = " ".join(chunks[index][0] for index in chosen)
            piece_text = " ".join(part for part in (body, tail) if part)
            if piece_text in seen or not piece_text:
                continue
            seen.add(piece_text)
            kept = dict(tail_slots)
            for index in chosen:
                kept.update(chunks[index][1])
            if any(piece_text.count(value) != 1 for value in kept.values()):
                continue            # 순서를 바꾸다 같은 글자가 둘이 되면 못 가른다
            piece = {k: v for k, v in example.items() if k != "inflection"}
            piece["text"], piece["slots"] = piece_text, kept
            yield piece, dropped, len(chunks) - keep, list(chosen) != order


def _finite(body, example, grammar):
    """몸통의 꼬리를 그 사례가 쓰는 마침꼴로 되돌린다. **아는 어간만** 본다.

    매김꼴(`주는`)만 되돌리면 이어지는 말(`주고`)을 못 읽는다. 꼬리마다 따로
    적지 않는다 — 언어팩이 그 어간의 꼴을 이미 다 계산하므로, 그 가운데 몸통의
    끝과 맞는 것을 찾아 그 사례가 쓰는 꼴로 바꿔 놓을 뿐이다.
    """
    yield body
    annotation = example.get("inflection")
    if not annotation or not grammar:
        return
    try:
        canonical = [form["text"] for form in
                     inflect(annotation["stem"], annotation["tense"], annotation["ending"],
                             grammar, kind=annotation["kind"])]
    except ValueError:
        return
    꼴 = set()
    for tense in grammar.get("tenses", {}):
        for ending in grammar.get("endings", {}):
            try:
                꼴 |= {form["text"] for form in
                      inflect(annotation["stem"], tense, ending, grammar,
                              kind=annotation["kind"])}
            except ValueError:
                continue
    for form in sorted(꼴, key=len, reverse=True):
        if body.endswith(form) and len(body) > len(form):
            for tail in canonical:
                yield body[:-len(form)] + tail


def _rename(value, prefix):
    """절마다 자리 이름이 겹치지 않게 앞에 표를 붙인다."""
    if isinstance(value, str):
        return "$" + prefix + value[1:] if value.startswith("$") else value
    if isinstance(value, list):
        return [_rename(item, prefix) for item in value]
    if isinstance(value, dict):
        # ``into`` declares a produced variable rather than referring to one
        # with a `$` prefix.  Clause composition must namespace it too, or a
        # later `$c0_basis` reference points at a value that was never bound.
        return {key: (prefix + item if key == "into" and isinstance(item, str)
                      else _rename(item, prefix))
                for key, item in value.items()}
    return value


def _clauses(body, grammar):
    """몸통을 절로 나눈다. 이음꼴로 끝나는 앞절과 나머지.

        내가 상대에게 구슬 두 개를 주고, 상대가 나에게 단추 한 개를 주는
        └────────── 앞절(`-고`) ──────────┘  └──────── 뒷절 ────────┘

    이음꼴 목록은 언어팩이 이미 적어 둔 것을 쓴다. 맞교환 전용 규칙이 아니다.
    """
    pieces = [piece.strip() for piece in body.split(",")]
    if len(pieces) < 2 or not all(pieces):
        return []
    꼬리들 = grammar.get("candidate_suffixes", [])
    if not all(any(piece.endswith(꼬리) for 꼬리 in 꼬리들) for piece in pieces[:-1]):
        return []
    return pieces


def _from_rule(parser, clause, 배운것):
    """절이 **이 대화에서 배운 동작**이면 그 뜻틀을 그대로 가져다 쓴다.

    문장을 새로 지어 다시 읽지 않는다. 이미 만들어 둔 동작·역할 얼개에 이 절의
    낱말을 앉힐 뿐이다 — 그래서 원문도, 그 동작이 어느 시점의 뜻이었는지도
    그대로 남는다. 동사마다 따로 처리하는 곳은 없다.
    """
    뜻표 = (배운것 or {}).get("뜻") or {}
    꼴표 = (배운것 or {}).get("꼴") or {}
    words = clause.strip().rstrip(".!?…").split()
    if not 뜻표 or len(words) < 2:
        return None
    stem = 꼴표.get(words[-1])
    쓸것 = 뜻표.get(stem)
    if 쓸것 is None:
        return None
    후보, _잘림 = _chunkings(words[:-1], parser.case_particles, parser.slot_particles)
    if not 후보:
        return None
    자리 = {particle_key(key, parser.slot_particles): value
           for key, value in 후보[0].items()}
    값, 앉힘 = dict(쓸것["값"]), {}
    for name, key in {**쓸것["빈자리"], **쓸것["채울자리"]}.items():
        if key not in 자리:
            return None            # 이 절이 그 자리를 안 짚었다
        값[name], 앉힘[name] = 자리[key], key
    # 배운 동작을 부를 때도 **절이 짚은 나머지 자리**를 봐야 한다. 안 보면
    # `내가 물건을 학교로 치우고` 의 `학교로` 가 조용히 버려지고 뜻풀이가 정해 둔
    # `상자` 가 쓰인다. 뜻풀이가 정한 값과 어긋나거나 뜻풀이에 없는 자리가 남으면
    # 우리가 고르지 않는다 — 못 읽은 것으로 드러낸다.
    for key, value in 자리.items():
        if key in 앉힘.values():
            continue
        name = next((n for n, k in 쓸것["자리"].items() if k == key), None)
        if name is None or 쓸것["값"].get(name) != value:
            return None
    자리표 = {**쓸것["자리"], **앉힘}
    # Keep both the expanded meaning (for compatibility and inspection) and
    # an executable call edge.  The runtime gets the latter, so a composed
    # natural definition reuses the referenced action's binding/execution
    # contract instead of reimplementing its effect in the outer action.
    reference_version = (배운것 or {}).get("때", {}).get(stem)
    return {"뜻": 쓸것["뜻"], "값": 값, "자리": 자리표, "빈자리": {},
            "채울자리": _open(값, 자리표, parser.placeholders),
            "호출": [{"action": stem, "definition_version": reference_version,
                     "role_slots": dict(자리표), "values": dict(값)}],
            "프로그램단계": [{"op": "call", "action": stem,
                              "definition_version": reference_version,
                              "roles": {slot: "$" + name
                                        for name, slot in 자리표.items()}}],
            "삼킴": sum(_marked(value, parser.case_particles, parser.slot_particles)
                      for value in 앉힘 and [값[name] for name in 앉힘]),
            "쓴동사": sorted({stem} | set(쓸것.get("쓴동사") or ()))}


def _compose(parser, body, 배운것=None):
    """절이 여럿인 몸통. **절마다 따로 읽고 자리말로 잇는다.**

    이미 아는 동작을 엮을 뿐이고 새 연산을 만들지 않는다. 두 절에 같은 자리말이
    나오면 **같은 것을 가리킨다** — 그래서 뒷절에서 주는이와 받는이가 뒤집히는
    일이 따로 적지 않아도 나온다. 자리말이 처음 나온 절의 조사가 그 자리의
    조사가 된다.
    """
    pieces = _clauses(body, parser.clause_grammar)
    if not pieces:
        return None
    읽은절, 역할조사 = [], {}
    for piece in pieces:
        읽음 = induce(parser, piece, 배운것)
        if 읽음 is None:
            return None
        읽은절.append(읽음)
    # **그 일을 한 쪽은 임자 자리에 선다.** 절에 먼저 나온 순서로 정하면
    # 방향을 뒤집어 적은 뜻풀이가 같은 결과를 낸다.
    말하는이 = parser.placeholders.get(parser.speaker_placeholder)
    if 말하는이 is not None:
        역할조사[말하는이] = particle_key(parser.doer_particle, parser.slot_particles)
    쓴조사 = set(역할조사.values())
    for 읽음 in 읽은절:
        for name, key in 읽음["채울자리"].items():
            역할 = parser.placeholders.get(읽음["값"].get(name))
            if 역할 is None or 역할 in 역할조사 or key in 쓴조사:
                continue
            역할조사[역할] = key
            쓴조사.add(key)
    # 자리말이 둘인데 조사가 하나면 사건이 둘을 못 가른다. 겹쳐 놓고 둘 다
    # 같은 값으로 채우면 서로 어긋나는 사실이 조용히 만들어진다 — 안 읽는다.
    for 읽음 in 읽은절:
        for name in 읽음["채울자리"]:
            역할 = parser.placeholders.get(읽음["값"].get(name))
            if 역할 is not None and 역할 not in 역할조사:
                return None
    triples, 값, 자리, 채울자리, 빈자리, 호출, 프로그램단계 = [], {}, {}, {}, {}, [], []
    for index, 읽음 in enumerate(읽은절):
        prefix = "c%d_" % index
        뜻 = 읽음["뜻"]
        rows = 뜻.get("triples") or ([뜻["triple"]] if "triple" in 뜻 else [])
        triples += [_rename(row, prefix) for row in rows]
        # A direct clause emits its declared facts.  A clause that reused an
        # earlier learned action keeps that action as an actual call step;
        # its expanded triples above remain the stable explanatory meaning,
        # not a second state transition.
        steps = 읽음.get("프로그램단계") or [{"op": "emit", "triples": rows}]
        프로그램단계 += [_rename(step, prefix) for step in steps]
        값.update({prefix + k: v for k, v in 읽음["값"].items()})
        자리.update({prefix + k: v for k, v in 읽음["자리"].items()})
        빈자리.update({prefix + k: v for k, v in 읽음["빈자리"].items()})
        for call in 읽음.get("호출") or []:
            호출.append({**call,
                         "role_slots": {prefix + key: value for key, value in
                                        (call.get("role_slots") or {}).items()},
                         "values": {prefix + key: value for key, value in
                                    (call.get("values") or {}).items()}})
        for name, key in 읽음["채울자리"].items():
            역할 = parser.placeholders.get(읽음["값"].get(name))
            채울자리[prefix + name] = 역할조사.get(역할, key)
    쓴동사 = sorted({stem for 읽음 in 읽은절 for stem in (읽음.get("쓴동사") or ())})
    return {"뜻": {"triples": triples}, "값": 값, "자리": 자리,
            "채울자리": 채울자리, "빈자리": 빈자리, "호출": 호출,
            "프로그램단계": 프로그램단계,
            "쓴동사": 쓴동사}


def induce(parser, body, 배운것=None):
    """몸통을 이미 아는 문장꼴로 읽는다. 읽히면 쓸 수 있는 뜻틀을 준다.

    ``배운것`` 은 이 대화에서 **먼저 설명받은 동작**들이다. 사례로 안 읽히면
    그것들로 읽어 본다 — 배운 동작이 다른 설명의 재료가 되는 길이다.

    가장 적게 지운 자름을 고른다. 더 지울수록 말을 더 삼키기 때문이다.
    순서를 그대로 둔 자름을 먼저 다 보고, 그것으로 안 되면 순서를 바꿔 본다 —
    흔한 쪽을 먼저 보는 것이 값도 싸고, 덜 흔든 읽기를 고르는 길이기도 하다.
    """
    # 절로 나뉘는 몸통은 **조합**이다. 배운 동작 하나로 먼저 읽으려 들면 그 하나가
    # 몸통을 통째로 삼킨다 — `상대에게 베풀고, 상대가 나` 가 한 이름이 된다.
    if _clauses(body, parser.clause_grammar):
        return _compose(parser, body, 배운것)
    found = _read_body(parser, body, False)
    # 조사를 넘어 삼킨 자름이 나왔으면 순서를 바꾼 자름도 보고 더 나은 쪽을 쓴다.
    # 먼저 나온 것을 그냥 쓰면 `상자로 물건을` 이 한 이름으로 굳는다.
    if found is None or found[0][2]:
        other = _read_body(parser, body, True)
        if other is not None and (found is None or other[0] < found[0]):
            found = other
    배운읽기 = _from_rule(parser, body, 배운것)
    if found is None:
        return 배운읽기
    # **순서로 정하지 않고 겨룬다.** 넓은 사례 틀은 아무 말이나 한 이름으로 삼켜
    # 맞기 때문에, 먼저 보는 쪽이 이기면 배운 동작이 영영 안 쓰인다.
    # 조사를 덜 넘은 읽기가 옳은 읽기다.
    if 배운읽기 is not None and 배운읽기.get("삼킴", 0) < found[0][2]:
        return 배운읽기
    return found[1]


def _compile(parser, example, piece):
    """조각 사례의 틀. 몸통마다 다시 짓지 않는다."""
    cache = parser.__dict__.setdefault("_조각틀", {})
    key = (example["text"], piece["text"])
    if key not in cache:
        cache[key] = parser.compile(piece, parser.data.get("numerals", {}),
                                    parser.slot_particles)
    return cache[key]


def _read_body(parser, body, reorder):
    from marco.language.numerals import parse_numeral
    particles = parser.case_particles
    groups = parser.slot_particles
    numerals = parser.data.get("numerals", {})
    best = None
    for example in parser.data["examples"]:
        # State facts and action-program examples are both legitimate
        # definition bodies.  The latter only declares a generic operation
        # shape; it does not name the action the user will teach.
        if not (asserted(example["meaning"]) or example["meaning"].get("program")):
            continue                # 물음도 뜻풀이도 몸통이 될 수 없다
        for piece, dropped, missing, reordered in _elisions(example, particles, groups, reorder):
            # A fully elided example leaves only a generic predicate tail
            # (for example, ``만드는``).  It has no typed role evidence and
            # would let an unrelated unknown verb masquerade as any newly
            # added domain action.  At least one retained semantic slot is
            # required for a learned definition body.
            if not piece["slots"]:
                continue
            # A retained role plus case marker alone (``내가`` / ``상대에게``)
            # is not a sentence body.  Its compiled capture can absorb an
            # arbitrary unknown verb after inflection normalisation.  Require
            # some non-slot, non-particle lexical material as well; this is a
            # structural guard shared by every pack example, not an action
            # word allowlist.
            literal = piece["text"]
            for value in piece["slots"].values():
                literal = literal.replace(str(value), "", 1)
            for particle in sorted(particles, key=len, reverse=True):
                literal = literal.replace(particle, "")
            if not literal.strip():
                continue
            patterns, meaning = _compile(parser, example, piece)
            for candidate in _finite(body, example, parser.inflection_grammar):
                for pattern in patterns:
                    match = pattern.fullmatch(candidate)
                    if not match:
                        continue
                    values = dict(match.groupdict())
                    # `하루가 연필` 을 한 이름으로 삼킨 자름은 **덜 좋은** 읽기지
                    # 못 읽는 것이 아니다. 잘라 버리면 `사과 상자` 같은 성한
                    # 이름까지 못 읽는다. 어느 자름이 옳은지는 겨뤄서 정한다.
                    삼킴 = sum(_marked(value, particles, groups) for value in values.values())
                    for name, annotated in piece["slots"].items():
                        if annotated.isdecimal():
                            values[name] = parse_numeral(values[name], numerals)
                    if any(value is None for value in values.values()):
                        continue
                    spans = _spans(piece)
                    자리 = {name: _particle_at(piece["text"], end, particles, groups)
                           for _s, end, name in spans}
                    자리 = {k: v for k, v in 자리.items() if v}
                    specificity = len(candidate) - sum(len(value) for value in match.groupdict().values())
                    # 적게 지운 것, 순서를 안 바꾼 것, 조사를 덜 넘은 것, 더 많이
                    # 못 박은 것 순.
                    score = (missing, reordered, 삼킴, -specificity)
                    if best is None or score < best[0]:
                        emitted = {"triples": [step for step in meaning.get("program", [])
                                                 if step.get("op") == "emit"]}
                        # ``뜻`` stays available to the old composition and
                        # conflict machinery; the runtime receives the full
                        # program separately and executes it once.
                        if emitted["triples"]:
                            emitted = {"triples": [triple for step in emitted["triples"]
                                                     for triple in step.get("triples", [])]}
                        else:
                            emitted = meaning
                        best = (score, {"뜻": emitted, "값": values, "자리": 자리,
                                        "채울자리": _open(values, 자리, parser.placeholders),
                                        "빈자리": dropped,
                                        "프로그램단계": deepcopy(meaning.get("program") or [])})
    return best


def _open(values, 자리, placeholders):
    """뜻풀이가 적어 둔 값 가운데 **자리말**인 것. 그 자리는 사건이 채운다.

        치우다는 물건을 상자로 옮기는 것이다
                 ^^^^ 자리말 — 물건이라는 이름의 물건이 아니다
                      ^^^^ 값 — 뜻풀이가 정한 곳

    자리인지 값인지는 **짜임으로는 안 갈린다.** `물건` 과 `상자` 는 문장에서
    똑같이 생겼다. 갈리는 것은 낱말의 성질이므로 언어팩이 낱말로 적는다.
    적히지 않은 낱말은 값으로 본다 — 사건이 딴 값을 대면 고르지 않고 묻는다.
    """
    return {name: key for name, key in 자리.items() if values.get(name) in placeholders}


def apply_rule(induced, 자리, 덮기=()):
    """사건이 짚은 자리로 뜻틀을 채운다. **못 채운 자리는 못 채웠다고 말한다.**

    자리 하나를 못 채웠다고 아무 일도 없었던 것이 아니다. `지연에게 베풀었다`
    는 누가 줬는지는 몰라도 무언가 일어났다고 말한다. 그것을 빈 사실 목록으로
    바꾸면 **해석 실패가 "변화 없음" 으로 둔갑한다** — 옛 값이 그대로 확정된다.
    그래서 둘을 갈라서 돌려주고, 못 채운 자리가 있으면 사실은 안 쓴다.
    """
    채울자리 = induced.get("채울자리", {})
    values, 충돌 = dict(induced["값"]), {}
    # 뜻풀이가 정한 값을 **사람이 그렇게 하라고 한 만큼만** 덮는다. 우리가 고르는
    # 것이 아니라 어디까지인지 물어서 받은 답이다.
    덮기 = dict(덮기 or {})
    for name, key in induced["자리"].items():
        if key in 덮기:
            values[name] = 덮기[key]
    for name in 채울자리:
        values.pop(name, None)                # 자리말은 값이 아니다. 비워 둔다
    # **자리말이 앉은 자리는 채울자리가 정한다.** 몸통에 적힌 조사를 그대로 쓰면
    # 두 절에 같은 자리말이 나와도 안 뒤집힌다 — `상대가 나에게` 의 `상대` 는
    # 앞절에서 `에게` 자리였으므로 여기서도 `에게` 로 채워야 한다.
    # 사건이 조사 하나에 준 값은 **그 조사를 비워 둔 자리**의 몫이다. 같은 조사에
    # 앉은 상수까지 그 값과 견주면, `물건을 상자로 옮기고 상자를 책상으로 옮기는`
    # 의 `상자` 가 사건의 `연필` 과 부딪친 것으로 잡힌다.
    열린조사 = set({**induced["빈자리"], **채울자리}.values())
    for name, key in {**induced["자리"], **induced["빈자리"], **채울자리}.items():
        if key not in 자리:
            continue
        if name in induced["빈자리"] or name in 채울자리 or key in 덮기:
            values[name] = 덮기.get(key, 자리[key])
        elif key not in 열린조사 and induced["값"].get(name) != 자리[key]:
            # 뜻풀이가 정한 값과 다른 값이다. 채우는 것이 아니라 바꾸는 것이므로
            # 말없이 어느 한쪽을 고르지 않는다.
            충돌[name] = {"뜻": induced["값"].get(name), "사건": 자리[key], "자리": key}
    빈자리 = {name: key for name, key in {**induced["빈자리"], **채울자리}.items()
             if name not in values}
    남은자리 = {key for key in 자리
             if key not in set(induced["자리"].values()) | set(induced["빈자리"].values())}
    # 자리말이 안 채워졌으면 그 자리는 **비워 둔 채로** 닿는 곳을 센다. 뜻풀이에
    # 적힌 `물건` 을 도로 넣으면 "물건이라는 것의 자리" 만 못 박고, 정작 무엇이
    # 움직였는지 모르는 채로 딴 값을 확정하게 된다.
    사실 = asserted(substitute(induced["뜻"], values))
    return {"사실": [] if (빈자리 or 충돌) else 사실, "빈자리": 빈자리,
            "충돌": 충돌, "남은자리": 남은자리, "닿는곳": 사실}


def asks(text, negation=None, verbs=None):
    """묻는 말인가. 설명받은 어간의 **묻기 전용 꼴**로 끝나면 묻는 말이다.

    물음표에만 기대면 안 된다 — `민수가 지연에게 베풉니까` 는 물음표가 없어도
    물음이고, 사건으로 읽으면 물어본 일이 실제로 일어난다.
    """
    words = text.strip().rstrip(".!?…").split()
    if not words:
        return False
    if negation and words[-1] in (negation.get("물음") or ()):
        return True
    return bool((verbs or {}).get(words[-1], {}).get("물음"))


def _chunkings(words, particles, groups, limit=12):
    """자리 나누기의 갈래들. 어느 자름이 옳은지 여기서는 못 정한다.

        사과 상자를   ->   [사][상자]   또는   [사과 상자]

    `사과` 의 `과` 가 조사인지 이름의 끝 글자인지는 이 낱말만 봐서는 안 갈린다.
    그러니 갈래를 다 내주고, **뜻풀이가 그 자리를 쓰는지**가 정하게 한다.
    """
    def walk(index, current, done):
        if len(done) > len(words):
            return
        if index == len(words):
            if not current:
                yield done
            return
        piece = split_particle(words[index], particles, groups)
        if piece is not None and piece[0]:
            value = " ".join(current + [piece[0]])
            if all(key != piece[1] for key, _v in done):
                yield from walk(index + 1, [], done + [(piece[1], value)])
        yield from walk(index + 1, current + [words[index]], done)

    out, 잘림 = [], False
    for reading in walk(0, [], []):
        if reading and reading not in out:
            out.append(reading)
        if len(out) >= limit:
            잘림 = True             # 다 못 봤다는 것을 숨기지 않는다
            break
    return [dict(reading) for reading in out], 잘림


def read_event(text, particles, groups, negation=None, verbs=None,
               plan=None, grammar=None):
    """조사가 자리를 짚고 남은 한 낱말이 움직임인 꼴. 사건은 이렇게 생겼다.

    **뜻을 몰라도 꼴은 안다.** 그래야 모르는 말을 만났을 때 "그 말을 모릅니다"
    라고 짚어 주고, 나중에 설명을 들으면 이어서 풀 수 있다. 뜻은 여기서
    정하지 않는다 — 쓰인 낱말을 그대로 돌려주고, 설명받은 어간과 잇는 일은
    활용표가 한다.

    꼴이 아닌 것은 안 읽는다. 앞 낱말이 조사를 안 달았으면(`단추 이야기는
    재밌다` 의 `단추`) 자리를 못 짚은 것이고, 못 짚으면 짐작하지 않는다.

    **묻는 말도 사건이 아니다.** 물음표가 없어도 그렇다 — `베풉니까` 는
    설명받은 어간의 물음꼴이므로 일어난 일이 아니다. 활용을 이을 때 어간만
    나르면 이 자리를 놓친다.

    자리를 어디서 끊을지는 여럿일 수 있다(`사과 상자를`). 갈래를 다 담아 두고
    고르는 일은 뜻풀이를 아는 쪽에 맡긴다.
    """
    words = text.strip().rstrip(".!?…").split()
    if not words or asks(text, negation, verbs):
        return None
    polarity, tail, modality = True, words[-1:], None
    # 아직 안 일어난 일. 꼴로 알아보고 **사실로 안 적는다.**
    if plan and len(words) > 2 and words[-1] in plan["맺음"]:
        어간 = _plan_stem(words[-2], verbs, plan, grammar)
        if 어간 is None:
            return None
        modality, tail, words = "planned", [어간], words[:-1]
    if negation and len(words) > 2 and words[-1] in negation["forms"]:
        stem = words[-2][:-len(negation["연결"])]
        if not words[-2].endswith(negation["연결"]) or not stem:
            return None
        polarity, tail, words = False, [stem], words[:-1]
    if len(words) < 2:
        return None
    후보, 잘림 = _chunkings(words[:-1], particles, groups)
    if not 후보:
        return None             # 조사 없는 낱말이 남으면 자리를 못 짚은 것이다
    # 자름이 너무 많아 다 못 봤으면 그렇다고 적어 둔다. 남은 하나를 유일한
    # 해석처럼 쓰면, 못 본 자름이 옳았을 때 틀린 값을 조용히 확정하게 된다.
    event = {"verb": tail[0], "자리": 후보[0], "자리후보": 후보, "잘림": 잘림}
    if modality:
        event["modality"] = modality
    return event if polarity else {**event, "polarity": False}


def _plan_stem(word, verbs, plan, grammar):
    """`베풀` 처럼 매김꼴 미래로 적힌 말의 어간. **아는 어간만** 되돌린다."""
    from marco.language.hangul import inflect
    for surface, found in (verbs or {}).items():
        stem = found["stem"] if isinstance(found, dict) else found
        try:
            꼴 = {form["text"] for tense in (grammar or {}).get("tenses", {})
                 for form in inflect(stem, tense, plan["연결"], grammar, kind="regular")}
        except ValueError:
            continue
        if word in 꼴:
            return stem
    return None


def _unknown_action_env(status, sid, span, utext, cands, complete, trunc, gaps):
    return {'schema': 'unknown-action-reading-v1', 'status': status, 'surface_id': sid,
            'source_scope': 'current_clause', 'offset_unit': 'unicode_codepoint',
            'unknown_span': span, 'unknown_text': utext, 'role_candidates': cands,
            'search_complete': complete, 'truncated': trunc, 'gaps': gaps}


def _unknown_action_gap(code, path, sid=None, status='gap', span=None, utext=None, complete=None):
    return _unknown_action_env(status, sid, span, utext, [], complete, False,
                               [{'code': code, 'path': path}])


def _unknown_action_finish(env, maxout):
    import json

    def size(e):
        return len(json.dumps(e, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))

    if size(env) <= maxout:
        return env
    orig = env['role_candidates']
    cands = list(orig)
    e = dict(env)
    e['gaps'] = list(env['gaps']) + [{'code': 'output_cap', 'path': None}]
    e['status'] = 'gap'
    e['search_complete'] = False
    while True:
        e['role_candidates'] = cands
        e['truncated'] = bool(env['truncated']) or len(cands) < len(orig)
        if size(e) <= maxout:
            return e
        if not cands:
            break
        cands.pop()
    omitted = bool(env['truncated']) or len(orig) > 0
    fb_complete = False if omitted else env['search_complete']
    return _unknown_action_env('gap', None, None, None, [], fb_complete, omitted,
                               [{'code': 'output_cap', 'path': None}])


def _unknown_action_scan(obj):
    stack, n = [obj], 0
    while stack:
        x = stack.pop()
        n += 1
        if n > 2048:
            return 'input_cap', n
        t = type(x)
        if t is dict or t is list:
            if n + len(x) + len(stack) > 2048:
                return 'input_cap', n
            if t is dict:
                for k, v in x.items():
                    if type(k) is not str or len(k) > 512:
                        return 'malformed', n
                    stack.append(v)
            else:
                stack.extend(x)
        elif t is str:
            if len(x) > 512:
                return 'input_cap', n
        elif not (t is int or t is bool or x is None):
            return 'malformed', n
    return None, n


def _unknown_action_strs(v, path, cap, nows, single):
    if type(v) is not list:
        return 'malformed', path
    if len(v) > cap:
        return 'input_cap', path
    for x in v:
        if type(x) is not str or not x or len(x) > 512:
            return 'malformed', path
        if single and len(x) != 1:
            return 'unsupported_boundary', path
        if nows and any(c.isspace() for c in x):
            return 'malformed', path
    if len(set(v)) != len(v):
        return 'malformed', path
    return None


def _unknown_action_name(v):
    return type(v) is str and 0 < len(v) <= 512


def _unknown_action_check(s):
    ceil = {'max_source_chars': 512, 'max_tokens': 40, 'max_case_groups': 8,
            'max_markers': 64, 'max_role_candidates': 64, 'max_search_steps': 4096,
            'max_json_nodes': 2048, 'max_output_bytes': 65536}
    keys = {'schema', 'surface_id', 'boundary', 'case_groups', 'roles',
            'known_action_surfaces', 'coreference_policy', 'limits'}
    if type(s) is not dict or set(s) != keys:
        return 'malformed', 'surface'
    if s['schema'] != 'unknown-action-surface-v1':
        return 'malformed', 'schema'
    if not _unknown_action_name(s['surface_id']):
        return 'malformed', 'surface_id'
    lim = s['limits']
    if type(lim) is not dict or set(lim) != set(ceil):
        return 'malformed', 'limits'
    for k, c in ceil.items():
        v = lim[k]
        if type(v) is not int or not 1 <= v <= c:
            return 'malformed', 'limits.' + k
    b = s['boundary']
    bkeys = {'kind', 'token_separator', 'terminators', 'question_marks',
             'clause_separators', 'excluded_final_forms', 'excluded_final_suffixes'}
    if type(b) is not dict or set(b) != bkeys:
        return 'malformed', 'boundary'
    if b['kind'] != 'final_token_case_groups_v1':
        return 'unsupported_boundary', 'boundary.kind'
    if b['token_separator'] != 'unicode_whitespace_v1':
        return 'unsupported_tokenizer', 'boundary.token_separator'
    for k in ('terminators', 'question_marks', 'clause_separators'):
        g = _unknown_action_strs(b[k], 'boundary.' + k, 64, True, True)
        if g:
            return g
    for k in ('excluded_final_forms', 'excluded_final_suffixes'):
        g = _unknown_action_strs(b[k], 'boundary.' + k, 64, False, False)
        if g:
            return g
    g = _unknown_action_strs(s['known_action_surfaces'], 'known_action_surfaces', 64, False, False)
    if g:
        return g
    if s['coreference_policy'] != 'exact_raw_value_v1':
        return 'unsupported_coreference_policy', 'coreference_policy'
    groups = s['case_groups']
    if type(groups) is not list:
        return 'malformed', 'case_groups'
    if len(groups) > min(8, lim['max_case_groups']):
        return 'input_cap', 'case_groups'
    ids, total = set(), 0
    for i, g in enumerate(groups):
        p = 'case_groups.%d' % i
        if type(g) is not dict or set(g) != {'id', 'markers'}:
            return 'malformed', p
        gid = g['id']
        if not _unknown_action_name(gid) or gid in ids:
            return 'malformed', p + '.id'
        ids.add(gid)
        r = _unknown_action_strs(g['markers'], p + '.markers', 64, True, False)
        if r:
            return r
        total += len(g['markers'])
    if total > min(64, lim['max_markers']):
        return 'input_cap', 'case_groups'
    roles = s['roles']
    if type(roles) is not list or len(roles) != len(groups):
        return 'malformed', 'roles'
    rkeys = {'case_group', 'slot', 'type_ref', 'presence', 'coreference_group'}
    cgs, slots = set(), set()
    for i, r in enumerate(roles):
        p = 'roles.%d' % i
        if type(r) is not dict or set(r) != rkeys:
            return 'malformed', p
        if not _unknown_action_name(r['case_group']) or r['case_group'] in cgs:
            return 'malformed', p + '.case_group'
        if not _unknown_action_name(r['slot']) or r['slot'] in slots:
            return 'malformed', p + '.slot'
        if not _unknown_action_name(r['type_ref']):
            return 'malformed', p + '.type_ref'
        if r['presence'] not in ('required', 'optional') or type(r['presence']) is not str:
            return 'malformed', p + '.presence'
        if r['coreference_group'] is not None and not _unknown_action_name(r['coreference_group']):
            return 'malformed', p + '.coreference_group'
        cgs.add(r['case_group'])
        slots.add(r['slot'])
    if cgs != ids:
        return 'malformed', 'roles'
    return None


def read_unknown_action(text, surface):
    try:
        return _unknown_action_read(text, surface)
    except Exception:
        return _unknown_action_gap('malformed', None)


def _unknown_action_read(text, surface):
    maxout = 65536

    def out(env):
        return _unknown_action_finish(env, maxout)

    if type(text) is not str:
        return out(_unknown_action_gap('malformed', 'text'))
    code, nodes = _unknown_action_scan(surface)
    if code:
        return out(_unknown_action_gap(code, 'surface'))
    bad = _unknown_action_check(surface)
    if bad:
        return out(_unknown_action_gap(bad[0], bad[1]))
    lim, sid = surface['limits'], surface['surface_id']
    maxout = lim['max_output_bytes']

    def gap(code, path, status='gap', span=None, utext=None, complete=None):
        return out(_unknown_action_gap(code, path, sid, status, span, utext, complete))

    if nodes > lim['max_json_nodes']:
        return gap('input_cap', 'limits.max_json_nodes')
    if len(text) > lim['max_source_chars']:
        return gap('input_cap', 'text')
    b = surface['boundary']
    qm, term, sep = set(b['question_marks']), set(b['terminators']), set(b['clause_separators'])
    i, j = 0, len(text)
    while i < j and text[i].isspace():
        i += 1
    while j > i and text[j - 1].isspace():
        j -= 1
    if i == j:
        return gap('empty_clause', None, 'no_match')
    if text[j - 1] in qm:
        return gap('question_mark', None, 'no_match')
    if text[j - 1] in term:
        j -= 1
        if j > i and text[j - 1] in term:
            return gap('unsupported_boundary', 'boundary.terminators')
    for c in text[i:j]:
        if c in qm:
            return gap('question_mark', None, 'no_match')
        if c in sep or c in term:
            return gap('out_of_scope_punctuation', None, 'no_match')
    toks, k = [], i
    while k < j:
        if text[k].isspace():
            k += 1
            continue
        s0 = k
        while k < j and not text[k].isspace():
            k += 1
        toks.append((s0, k))
        if len(toks) > lim['max_tokens']:
            return gap('input_cap', 'text')
    if len(toks) < 2:
        return gap('too_few_tokens', None, 'no_match')
    us, ue = toks[-1]
    ut, span = text[us:ue], [us, ue]
    if (ut in surface['known_action_surfaces'] or ut in b['excluded_final_forms']
            or any(ut.endswith(x) for x in b['excluded_final_suffixes'])):
        return gap('declared_excluded_final', None, 'no_match', span, ut)
    groups, rlist = surface['case_groups'], surface['roles']
    roles = {r['case_group']: r for r in rlist}
    ttoks = toks[:-1]
    n, maxsteps, cap = len(ttoks), lim['max_search_steps'], lim['max_role_candidates']
    stack = [(0, None, (), ())]
    steps, cands, seen, trunc, work = 0, [], set(), False, False
    while stack:
        ti, cs, used, binds = stack.pop()
        steps += 1
        if steps > maxsteps:
            work = True
            break
        if ti == n:
            if cs is not None or not binds:
                continue
            usedg = {x[0] for x in binds}
            if any(r['presence'] == 'required' and r['case_group'] not in usedg for r in rlist):
                continue
            cv, ok = {}, True
            for gid, st, ve, e in binds:
                cg = roles[gid]['coreference_group']
                if cg is not None:
                    val = text[st:ve]
                    if cv.setdefault(cg, val) != val:
                        ok = False
                        break
            if not ok or binds in seen:
                continue
            seen.add(binds)
            if len(cands) >= cap:
                trunc = True
                break
            bl = []
            for gid, st, ve, e in binds:
                r = roles[gid]
                bl.append({'slot': r['slot'], 'value': text[st:ve], 'span': [st, ve],
                           'marker_span': [ve, e], 'chunk_span': [st, e],
                           'case_group': gid, 'type_ref': r['type_ref'],
                           'presence': r['presence'],
                           'coreference_group': r['coreference_group']})
            cands.append({'bindings': bl,
                          'omitted_slots': [r['slot'] for r in rlist if r['case_group'] not in usedg]})
            continue
        s, e = ttoks[ti]
        start = s if cs is None else cs
        kids = []
        for gi, g in enumerate(groups):
            if gi in used:
                continue
            for m in g['markers']:
                steps += 1
                if steps > maxsteps:
                    work = True
                    break
                if e - len(m) > s and text.endswith(m, s, e):
                    kids.append((ti + 1, None, used + (gi,),
                                 binds + ((g['id'], start, e - len(m), e),)))
            if work:
                break
        if work:
            break
        kids.append((ti + 1, start, used, binds))
        stack.extend(reversed(kids))
    gaps = []
    if trunc:
        gaps.append({'code': 'candidate_limit', 'path': 'limits.max_role_candidates'})
    elif work:
        gaps.append({'code': 'work_limit', 'path': 'limits.max_search_steps'})
    complete = not (trunc or work)
    if gaps:
        status = 'gap'
    elif cands:
        status = 'read'
    else:
        status = 'no_match'
        gaps = [{'code': 'no_structural_candidate', 'path': None}]
    return out(_unknown_action_env(status, sid, span, ut, cands, complete, trunc, gaps))
