"""Offline, source-only surface candidate induction (graph-native, inactive).

Finds repeated literal contexts (prefix, suffix) around a varying contiguous
nonempty substring in raw, unlabeled sentence strings. Candidates are inert
graph data: they carry no semantics, roles, truth or equivalence claims.
Only generic string statistics are used; no language-specific rules.
"""

import hashlib
import json

SCHEMA = "marco-surface-candidates-v1"
MAX_SENTENCES = 64
MAX_CODEPOINTS = 128
MAX_UTF8_BYTES = 512
MAX_WORK = 1000000
MAX_CONTEXTS = 65536


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _exact_int(value, low, high, name):
    if type(value) is not int or not (low <= value <= high):
        raise ValueError("%s must be an int in %d..%d" % (name, low, high))
    return value


def _validate_sentences(sentences):
    if type(sentences) is not list:
        raise ValueError("sentences must be a list")
    if len(sentences) > MAX_SENTENCES:
        raise ValueError("too many sentences")
    out = []
    for item in sentences:
        if type(item) is not str:
            raise ValueError("each sentence must be a str")
        if not item:
            raise ValueError("empty sentence")
        if len(item) > MAX_CODEPOINTS:
            raise ValueError("sentence too long")
        try:
            encoded = item.encode("utf-8", "strict")
        except (UnicodeEncodeError, UnicodeError):
            raise ValueError("malformed unicode in sentence") from None
        if len(encoded) > MAX_UTF8_BYTES:
            raise ValueError("sentence too large in utf-8")
        out.append((item, encoded))
    return out


def _common_prefix_len(a, b):
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _common_suffix_len(a, b):
    n = min(len(a), len(b))
    i = 0
    while i < n and a[len(a) - 1 - i] == b[len(b) - 1 - i]:
        i += 1
    return i


def _candidate_id(prefix, suffix):
    blob = json.dumps([prefix, suffix], ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return "candidate:" + _sha(blob)


def induce(sentences, *, min_support=3, max_candidates=64):
    """Propose top-K inactive surface substitution candidates.

    max_candidates is a top-K proposal cut; unreturned structures are not
    claimed invalid. Raises ValueError on any invalid input or when the
    finite work/context limits would be exceeded (no partial output).
    """
    validated = _validate_sentences(sentences)
    min_support = _exact_int(min_support, 2, 64, "min_support")
    max_candidates = _exact_int(max_candidates, 1, 64, "max_candidates")

    unique = {}
    for text, encoded in validated:
        if text not in unique:
            unique[text] = _sha(encoded)
    # Deterministic order independent of input order.
    texts = sorted(unique, key=lambda t: (unique[t], t))
    sources = [{"id": "source:" + unique[t], "text": t, "sha256": unique[t]}
               for t in texts]

    work = 0
    groups = {}
    n = len(texts)
    for i in range(n):
        a = texts[i]
        for j in range(i + 1, n):
            b = texts[j]
            work += 1
            if work > MAX_WORK:
                raise ValueError("work limit exceeded")
            limit = min(len(a), len(b)) - 1
            if limit < 1:
                continue
            p = min(_common_prefix_len(a, b), limit)
            s = min(_common_suffix_len(a, b), limit)
            for pp in range(p + 1):
                max_ss = min(s, limit - pp)
                for ss in range(max_ss + 1):
                    if pp == 0 and ss == 0:
                        continue
                    work += 1
                    if work > MAX_WORK:
                        raise ValueError("work limit exceeded")
                    key = (a[:pp], a[len(a) - ss:] if ss else "")
                    members = groups.get(key)
                    if members is None:
                        if len(groups) >= MAX_CONTEXTS:
                            raise ValueError("context limit exceeded")
                        members = set()
                        groups[key] = members
                    members.add(i)
                    members.add(j)

    scored = []
    for (prefix, suffix) in sorted(groups):
        work += 1
        if work > MAX_WORK:
            raise ValueError("work limit exceeded")
        members = groups[(prefix, suffix)]
        evidence = []
        for idx in sorted(members):
            work += 1
            if work > MAX_WORK:
                raise ValueError("work limit exceeded")
            text = texts[idx]
            start = len(prefix)
            end = len(text) - len(suffix)
            if start >= end:
                continue
            if not (text.startswith(prefix) and text.endswith(suffix)):
                continue
            filler = text[start:end]
            evidence.append((filler, sources[idx]["id"], start, end))
        fillers = sorted(set(e[0] for e in evidence))
        # Unique texts with a shared context imply distinct fillers.
        if len(fillers) < min_support or len(fillers) != len(evidence):
            continue
        scored.append((-len(fillers), -(len(prefix) + len(suffix)),
                       prefix, suffix, fillers, evidence))
    scored.sort(key=lambda r: (r[0], r[1], r[2], r[3]))

    candidates = []
    for _, _, prefix, suffix, fillers, evidence in scored[:max_candidates]:
        evidence.sort(key=lambda e: (e[1], e[0]))
        candidates.append({
            "id": _candidate_id(prefix, suffix),
            "prefix": prefix,
            "suffix": suffix,
            "fillers": list(fillers),
            "evidence": [{"source": e[1], "start": e[2], "end": e[3]}
                         for e in evidence],
        })

    return {"schema": SCHEMA, "active": False, "semantics": None,
            "sources": sources, "candidates": candidates}
