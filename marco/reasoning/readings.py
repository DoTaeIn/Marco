"""Observation identity and the reading ledger (data only; no parser, no engine).

An observation owns its archived raw parsed meaning.  ``Obs`` is a ``str`` that carries the identity of its
observation slot (``oid``) and the active reading revision (``rev``), so lists of observations stay lists of
strings while every historical read can be routed by identity instead of by source text.  ``Obs`` compares
equal to a plain string by text, but two ``Obs`` are equal only when text, slot and revision all agree; the
replay and verb caches (keyed by tuples of sources) therefore see a revision change even when text is equal.
"""
import hashlib
import json
import re

TENTATIVE = "~cur"          # the provisional identity of the utterance being decided (never persisted)
REASONS = frozenset({"initial", "correction", "referent_resolution", "legacy_source_shared",
                     "candidate_reading", "unavailable"})
CARRIED_REASONS = frozenset({"candidate_reading", "referent_resolution"})
MAX_BYTES = 16 * 1024 * 1024
_ID = re.compile(r"^o[1-9][0-9]*$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class ReadingUnavailable(ValueError):
    """A historical operation needs an original reading this conversation never archived."""


class Obs(str):
    def __new__(cls, text="", oid=None, rev=1, reading=None, reason=None):
        self = super().__new__(cls, text)
        self.oid, self.rev, self.reading, self.reason = oid, rev, reading, reason
        return self

    def __getnewargs__(self):
        return (str(self), self.oid, self.rev, self.reading, self.reason)

    def __eq__(self, other):
        if isinstance(other, Obs):
            return str.__eq__(self, other) and self.oid == other.oid and self.rev == other.rev
        return str.__eq__(self, other)

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    __hash__ = str.__hash__

    def strip(self, *chars):
        return Obs(str.strip(self, *chars), self.oid, self.rev, self.reading, self.reason)


def oid_of(source):
    return getattr(source, "oid", None)


def tentative(text):
    return text if oid_of(text) is not None else Obs(str(text), TENTATIVE)


def grammar_fingerprint(parser):
    """SHA256 of the installed parser's actual grammar (data plus language pack)."""
    from marco.storage.overlay import dumps
    return hashlib.sha256(dumps({"data": parser.data, "language_pack": parser.language_pack})
                          .encode("utf-8")).hexdigest()


def make_record(oid, revision, source, parsed, *, base, head, reason, prior=None, unavailable=False,
                grammar=None):
    """``grammar`` None means the original grammar is unknown (never today's grammar)."""
    return {"observation_id": oid, "reading_revision": revision, "source": str(source),
            "parser_base_sha256": base, "installed_memory_head": head, "parser_grammar_sha256": grammar,
            "parsed": None if unavailable else parsed, "reason": reason,
            "prior_reading_id": prior, "unavailable": bool(unavailable)}


def _bad():
    return ValueError("invalid_reasoning_context_snapshot")


_USABLE_KEYS = ("verb", "몸통", "evidence", "유도", "쓴동사", "참조", "프로그램")


def _text(value):
    return isinstance(value, str) and bool(value)


def _nonneg_int(value):
    return type(value) is int and value >= 0


def _string_map(value):
    return isinstance(value, dict) and all(_text(k) and isinstance(v, str) for k, v in value.items())


def _versions(value):
    return isinstance(value, dict) and all(_text(k) and (v is None or _nonneg_int(v))
                                           for k, v in value.items())


def _step(step):
    """A step is a dict with a string op; known shared-schema containers must have their shape."""
    if not isinstance(step, dict) or not isinstance(step.get("op"), str):
        return False
    if "triples" in step and not (isinstance(step["triples"], list) and all(
            isinstance(t, (list, tuple)) and len(t) == 3 for t in step["triples"])):
        return False
    if "roles" in step and not _string_map(step["roles"]):
        return False
    if "definition_version" in step and not (step["definition_version"] is None
                                             or _nonneg_int(step["definition_version"])):
        return False
    return all(isinstance(step[k], str) for k in ("action", "into") if k in step)


def _check_programs(programs, parsed):
    """Structural (data-only) check of a snapshot's compiled definition programs."""
    limit = len(parsed.get("정의") or []) if isinstance(parsed, dict) and isinstance(
        parsed.get("정의"), list) else None
    for ordinal, compiled in programs.items():
        if not (isinstance(ordinal, str) and ordinal.isdigit() and ascii_digits(ordinal)):
            raise _bad()
        if limit is not None and int(ordinal) >= limit:
            raise _bad()
        usable, origins = compiled.get("usable"), compiled.get("origins")
        if not isinstance(usable, dict) or not isinstance(origins, dict):
            raise _bad()
        if any(key not in usable for key in _USABLE_KEYS) or not _text(usable["verb"]) \
                or not _text(usable["몸통"]) or not isinstance(usable["evidence"], dict) \
                or not isinstance(usable["유도"], dict) or not isinstance(usable["참조"], dict) \
                or not isinstance(usable["쓴동사"], list) \
                or any(not isinstance(v, str) for v in usable["쓴동사"]):
            raise _bad()
        if limit is not None:
            rule = parsed["정의"][int(ordinal)]
            if not isinstance(rule, dict) or rule.get("verb") != usable["verb"]:
                raise _bad()
        program = usable["프로그램"]
        signature = program.get("signature") if isinstance(program, dict) else None
        if (not isinstance(program, dict) or program.get("schema") != "nai-action-program-v1"
                or program.get("action") != usable["verb"]
                or not isinstance(signature, dict)
                or any(not _string_map(signature.get(k))
                       for k in ("role_slots", "open_roles", "fixed_values"))
                or not _versions(program.get("references")) or not _versions(usable["참조"])
                or not (program.get("definition_version") is None or _nonneg_int(program["definition_version"]))
                or not isinstance(program.get("definition_evidence"), dict)
                or not isinstance(program.get("calls"), list)
                or any(not isinstance(c, dict) for c in program["calls"])
                or not isinstance(program.get("steps"), list)
                or any(not _step(s) for s in program["steps"])):
            raise _bad()
        for stem, origin in origins.items():
            if (not isinstance(stem, str) or not isinstance(origin, list) or len(origin) != 2
                    or not isinstance(origin[0], str) or type(origin[1]) is not int):
                raise _bad()
        try:
            json.dumps(compiled, allow_nan=False)
        except (TypeError, ValueError):
            raise _bad() from None


def ascii_digits(text):
    return text.isascii()


def validate_ledger(texts, ids, ledger, *, max_turns, base=None, head_limit=None):
    """Return the normalized ledger or raise before any context state is touched."""
    if not (isinstance(ids, list) and len(ids) == len(texts) and len(set(ids)) == len(ids)
            and all(isinstance(i, str) and _ID.match(i) for i in ids)):
        raise _bad()
    if not isinstance(ledger, dict) or not isinstance(ledger.get("records"), dict):
        raise _bad()
    records, following = ledger["records"], ledger.get("next")
    if (type(following) is not int or following <= max((int(i[1:]) for i in ids), default=0)
            or set(records) != set(ids)):
        raise _bad()
    total = 0
    for text, oid in zip(texts, ids):
        entry = records[oid]
        versions = entry.get("versions") if isinstance(entry, dict) else None
        active = entry.get("active") if isinstance(entry, dict) else None
        if (not isinstance(versions, list) or not versions or type(active) is not int
                or not 1 <= active <= len(versions)):
            raise _bad()
        total += len(versions)
        for position, record in enumerate(versions, 1):
            if (not isinstance(record, dict) or record.get("observation_id") != oid
                    or record.get("reading_revision") != position
                    or not isinstance(record.get("source"), str) or not record["source"].strip()
                    or record.get("reason") not in REASONS
                    or not isinstance(record.get("unavailable"), bool)):
                raise _bad()
            if record.get("parser_base_sha256") is not None and (
                    not isinstance(record["parser_base_sha256"], str)
                    or (base is not None and record["parser_base_sha256"] != base)):
                raise _bad()
            memory = record.get("installed_memory_head")
            if memory is not None and (type(memory) is not int or memory < 0
                                       or (head_limit is not None and memory > head_limit)):
                raise _bad()
            prior = record.get("prior_reading_id")
            if prior != ([oid, position - 1] if position > 1 else None):
                raise _bad()
            parsed = record.get("parsed")
            if record["unavailable"] != (parsed is None):
                raise _bad()
            if parsed is not None and (not isinstance(parsed, dict)
                                       or not isinstance(parsed.get("facts", []), list)
                                       or any(not isinstance(row, dict) or not isinstance(row.get("triple"), list)
                                              or len(row["triple"]) != 3 for row in parsed.get("facts", []))):
                raise _bad()
            grammar = record.get("parser_grammar_sha256")
            if grammar is not None and not (isinstance(grammar, str) and _SHA.match(grammar)):
                raise _bad()
            programs = record.get("programs", {})
            if not isinstance(programs, dict) or any(not isinstance(v, dict) for v in programs.values()):
                raise _bad()
            _check_programs(programs, parsed)
            lost = record.get("programs_unavailable", [])
            if not isinstance(lost, list) or any(not isinstance(n, str) or not n.isdigit() for n in lost):
                raise _bad()
            if (position == active and not record["unavailable"]
                    and record["reason"] != "legacy_source_shared" and isinstance(parsed, dict)):
                events = parsed.get("사건")
                event = events[0] if type(events) is list and len(events) == 1 else None
                reading = event.get("structural_reading") if isinstance(event, dict) else None
                if (isinstance(event, dict) and "structural_reading" in event
                        and "selected_action_binding" in event
                        and isinstance(reading, dict)
                        and reading.get("schema") == "unknown-action-reading-v1"
                        and reading.get("status") == "read"
                        and reading.get("search_complete") is True
                        and reading.get("truncated") is False
                        and type(reading.get("gaps")) is list and reading["gaps"] == []
                        and isinstance(event["selected_action_binding"], dict)):
                    source = record["source"]
                    span = reading.get("unknown_span")
                    unknown = reading.get("unknown_text")
                    if not (type(span) is list and len(span) == 2
                            and all(type(n) is int for n in span)
                            and 0 < span[0] < span[1] <= len(source)
                            and type(unknown) is str and unknown
                            and not any(c.isspace() for c in unknown)
                            and source[span[0]:span[1]] == unknown
                            and event.get("verb") == unknown
                            and source[span[0] - 1].isspace()
                            and len(source[span[1]:].strip()) <= 1):
                        raise _bad()
        if versions[active - 1]["source"].strip() != text.strip():
            raise _bad()
    # Second pass: origin references must name actual ledger records.
    for entry in records.values():
        for record in entry["versions"]:
            for compiled in (record.get("programs") or {}).values():
                expected = set()
                for call in compiled["usable"]["프로그램"]["calls"]:
                    version = call.get("definition_version")
                    if not isinstance(call.get("action"), str) or not (
                            version is None or _nonneg_int(version)):
                        raise _bad()
                    expected.add("%s@%s" % (call["action"], version))
                if set(compiled["origins"]) != expected:
                    raise _bad()
                for stem, origin in compiled["origins"].items():
                    target = records.get(origin[0])
                    if (not isinstance(origin[0], str) or target is None or type(origin[1]) is not int
                            or not 1 <= origin[1] <= len(target["versions"])):
                        raise _bad()
                    actions = {c["action"] for c in compiled["usable"]["프로그램"]["calls"]
                               if isinstance(c.get("action"), str)
                               and (c.get("definition_version") is None
                                    or _nonneg_int(c.get("definition_version")))
                               and "%s@%s" % (c["action"], c.get("definition_version")) == stem}
                    defined = (target["versions"][origin[1] - 1].get("parsed") or {}).get("정의")
                    if not actions or not isinstance(defined, list) or not any(
                            isinstance(rule, dict) and rule.get("verb") in actions for rule in defined):
                        raise _bad()
    if total > max_turns * 8 or len(json.dumps(ledger, allow_nan=False)) > MAX_BYTES:
        raise _bad()
    return {"next": following, "records": records}


def legacy_ledger(texts, readings, *, base, head):
    """A bare pre-v11 context: only a source-keyed alternative choice may exist, never the original reads."""
    records = {}
    ids = ["o%d" % (i + 1) for i in range(len(texts))]
    for oid, text in zip(ids, texts):
        chosen = (readings or {}).get(text.strip())
        records[oid] = {"active": 1, "versions": [make_record(
            oid, 1, text, chosen, base=base, head=None,
            reason="legacy_source_shared" if chosen is not None else "unavailable",
            unavailable=chosen is None)]}
    return ids, {"next": len(texts) + 1, "records": records}
