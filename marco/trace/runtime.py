"""Trace-only runtime and provenance metadata, supplied by the trusted caller.

Selected model/encoder/realizer identities never come from the host or an
environment default. Missing declarations remain null with granular gaps.
``provenance_complete`` describes supplied metadata, not its truth, semantic
adequacy, or independent verification. No installed head implies rule use.

Operational build/pack hashing and legacy host inventory helpers are retained;
inventory does not establish what was selected. ``first_stamp`` is compatible
but now explicitly marks unknown selected components. No engine is imported.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
REALIZER = ROOT / "marco" / "language" / "realizer"
VERSION_FILE = ROOT / "mco" / "_version.py"
ENCODER_DEFAULT = "문자"

# Components whose output is not a function of the recorded inputs. A turn that
# used one is stamped replay_status = approximate, naming the component.
NONDETERMINISTIC = {
    "web_research": "goal_runtime research reads the open web (the gate stubs it)",
    "realizer_learning": "the realizer learns expressions from user sentences (live learning)",
    "semantic_backend": "semantic_parser ran a backend other than the structural one (an injected model)",
}
# semantic_parser backends whose output is a function of the input text alone.
DETERMINISTIC_SEMANTIC = frozenset({"local-structural-semantic-parser-v1", "no-token-semantic-parser"})

_cache = {}


def _sha256_file(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def build():
    """The git build hash of this checkout, once per process."""
    if "build" not in _cache:
        value = os.environ.get("MARCO_BUILD")
        if not value:
            try:
                value = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                                       capture_output=True, text=True, timeout=10).stdout.strip()
                dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                                       capture_output=True, text=True, timeout=10).stdout.strip()
                if dirty:
                    value += "+dirty"
            except (OSError, subprocess.SubprocessError):
                value = "unknown"
        _cache["build"] = value or "unknown"
    return _cache["build"]


def version():
    """The release version ``mco/_version.py`` declares (``__version__``), once per process; None without it."""
    if "version" not in _cache:
        try:
            found = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", VERSION_FILE.read_text(encoding="utf-8"))
        except OSError:
            found = None
        _cache["version"] = found.group(1) if found else None
    return _cache["version"]


def release(pack_file=None):
    """The release stamp: the declared version, the build, and the pack digest."""
    return {"version": version(), "build": build(), "pack_digest": pack_digest(pack_file)}


def _release_of(path):
    try:
        declared = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return ((declared.get("version") or {}).get("release")) if isinstance(declared, dict) else None


def pack_digest(path):
    """SHA-256 of a pack file's bytes, cached per (path, size, mtime)."""
    if path is None:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = ("pack", str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _cache:
        _cache[key] = _sha256_file(path)
    return _cache[key]


def encoder():
    return os.environ.get("KG_ENCODER", ENCODER_DEFAULT)


def pack_stem(pack):
    """``styles/english.json`` -> ``english``."""
    return Path(str(pack)).stem if pack else None


def realizer_version(stem):
    """The realizer declarations of a language, by schema and digest; None if there are none."""
    if not stem:
        return None
    key = ("realizer", stem)
    if key not in _cache:
        path, meaning = REALIZER / (stem + ".json"), REALIZER / "meaning.json"
        if not path.is_file() or stem == "meaning":
            _cache[key] = None
        else:
            try:
                meaning_schema = json.loads(meaning.read_text(encoding="utf-8")).get("schema")
            except (OSError, ValueError):
                meaning_schema = None
            _cache[key] = {"declarations": "marco/language/realizer/%s.json" % stem,
                           "sha256": _sha256_file(path)[:16],
                           "release": _release_of(path),
                           "meaning_schema": meaning_schema,
                           "meaning_sha256": _sha256_file(meaning)[:16] if meaning.is_file() else None,
                           "meaning_release": _release_of(meaning)}
    return _cache[key]


def stamp(pack):
    """The fields every event carries."""
    return {"build": build(), "pack": pack}


def first_stamp(pack, *, pack_file=None, model_digest=None, approximate=(), runtime_stamp=None):
    """Compatible stamp entry point; selected components come only from explicit caller declarations.

    The old model_digest argument describes parser source assets, not the
    selected graph's content fingerprint. Keep it distinctly labelled.
    Host inventory helpers remain available, but never establish what ran.
    """
    out = contract_provenance(runtime_stamp, pack=pack)["first"]
    out["source_model_digest"] = plain_json(model_digest, "source_model_digest")
    if pack_file is not None:
        out["pack_digest"] = pack_digest(pack_file)
    if approximate:
        out["approximate"] = sorted(set(approximate))
        out["replay_status"] = "approximate"
    return out


# ---------------------------------------------------------------------------
# trace contract: the selected runtime and what an answer used, as the trusted caller declares them
# ---------------------------------------------------------------------------
class TraceContractError(ValueError):
    """Caller-supplied trace metadata (stamp, provenance, prewritten input, pending ids) breaks the contract."""


COMPLETE, INCOMPLETE = "provenance_complete", "provenance_incomplete"
# The selected runtime the caller must name; a leaf not supplied stays null and is listed as missing.
SELECTED = (("model", ("content_fingerprint", "effective_key")),
            ("encoder", ("declaration_digest", "reference")),
            ("realizer", ("declaration_digest", "reference")))
# What an answer used, declared by the caller; a section not supplied is missing, an empty one is "none".
SECTIONS = {"used_readings": list, "assumptions": list, "rules": list, "sources": list,
            "used_learning": list, "composition": list, "criterion": dict, "installed_memory_head": dict}
CRITERION_KEYS = ("id", "scope")
ROW_FIELDS = {
    "used_readings": {"observation_id": str, "reading_revision": int,
                      "model_content_fingerprint": str, "memory_head": dict},
    "used_learning": {"candidate_id": str, "rule_id": str, "rule_revision": int,
                      "accepted_change_id": str, "teaching": dict},
    "rules": {"id": str, "declaration_digest": str},
    "composition": {"reference": str, "declaration_digest": str},
    "sources": {"source_id": str, "observation_id": str, "span": list, "text": str},
}


def plain_json(value, name="value", _ancestors=(), _depth=0):
    """A deep copy of ``value`` when it is plain JSON (dict with str keys, list, str, bool, int, finite float, None);
    anything else raises ``TraceContractError`` rather than being stringified."""
    if _depth > 64:
        raise TraceContractError("%s: metadata nesting limit" % name)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise TraceContractError("%s: non-finite number" % name)
        return value
    if isinstance(value, list):
        if id(value) in _ancestors:
            raise TraceContractError("%s: cyclic metadata" % name)
        return [plain_json(item, "%s[%d]" % (name, i), _ancestors + (id(value),), _depth + 1)
                for i, item in enumerate(value)]
    if isinstance(value, dict):
        if id(value) in _ancestors:
            raise TraceContractError("%s: cyclic metadata" % name)
        for key in value:
            if not isinstance(key, str):
                raise TraceContractError("%s: key %r is not a string" % (name, key))
        return {key: plain_json(item, "%s.%s" % (name, key), _ancestors + (id(value),), _depth + 1)
                for key, item in value.items()}
    raise TraceContractError("%s: %s is not plain JSON" % (name, type(value).__name__))


def _required(row, fields, prefix, missing):
    for name, kind in fields.items():
        value = row.get(name)
        if value is None or kind is str and not value:
            missing.append(prefix + "." + name)
        elif not isinstance(value, kind) or kind is int and isinstance(value, bool):
            raise TraceContractError("%s.%s has an invalid type" % (prefix, name))


def _row_gaps(name, rows, missing):
    for index, row in enumerate(rows):
        prefix = "provenance.%s[%d]" % (name, index)
        if not isinstance(row, dict):
            raise TraceContractError(prefix + " must be an object")
        if name == "sources" and "kind" in row:
            if type(row["kind"]) is not str or row["kind"] != "dialogue_input":
                raise TraceContractError(prefix + ".kind is not a supported source kind")
            allowed = {"kind": str, "source_id": str, "input_event_id": str, "conversation_id": str,
                       "turn": int, "text": str, "sha256": str, "span": list}
            for key in row:
                if key not in allowed:
                    raise TraceContractError("%s.%s is not allowed for dialogue_input" % (prefix, key))
            _required(row, allowed, prefix, missing)
            for key in ("source_id", "input_event_id", "conversation_id"):
                if isinstance(row.get(key), str) and len(row[key]) > 128:
                    raise TraceContractError("%s.%s is too long" % (prefix, key))
            turn = row.get("turn")
            if isinstance(turn, int) and not isinstance(turn, bool) and not 1 <= turn <= 65536:
                raise TraceContractError(prefix + ".turn is out of range")
            text = row.get("text")
            if isinstance(text, str) and len(text) > 32768:
                raise TraceContractError(prefix + ".text is too long")
            digest = row.get("sha256")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise TraceContractError(prefix + ".sha256 must be 64 lowercase hex characters")
            if isinstance(text, str) and text and isinstance(digest, str):
                try:
                    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
                except UnicodeEncodeError:
                    raise TraceContractError(prefix + ".text is not encodable as UTF-8")
                if actual != digest:
                    raise TraceContractError(prefix + ".sha256 does not match text")
            span = row.get("span")
            if isinstance(span, list):
                if len(span) != 2 or any(type(x) is not int for x in span):
                    raise TraceContractError(prefix + ".span must be [start, end] offsets")
                limit = 65536
                if isinstance(text, str):
                    limit = min(limit, len(text))
                if not 0 <= span[0] <= span[1] <= limit:
                    raise TraceContractError(prefix + ".span must be [start, end] offsets")
            continue
        _required(row, ROW_FIELDS[name], prefix, missing)
        if name == "used_learning" and isinstance(row.get("teaching"), dict):
            _required(row["teaching"], {"conversation_id": str, "turn_id": str}, prefix + ".teaching", missing)
        if name == "used_readings" and isinstance(row.get("memory_head"), dict):
            _head_gaps(row["memory_head"], prefix + ".memory_head", missing)
        revision = row.get("reading_revision" if name == "used_readings" else "rule_revision")
        minimum = 1 if name == "used_readings" else 0
        if isinstance(revision, int) and not isinstance(revision, bool) and revision < minimum:
            raise TraceContractError(prefix + ": invalid revision")
        if name == "sources" and isinstance(row.get("span"), list):
            span = row["span"]
            if len(span) != 2 or any(type(x) is not int for x in span) or not 0 <= span[0] <= span[1]:
                raise TraceContractError(prefix + ".span must be [start, end] offsets")


def _head_gaps(head, prefix, missing):
    if head.get("attached") is False:
        if "seq" in head or "change_id" in head:
            raise TraceContractError(prefix + ": unattached memory has no head")
        return
    _required(head, {"seq": int}, prefix, missing)
    if isinstance(head.get("seq"), int) and not isinstance(head.get("seq"), bool):
        if head["seq"] < 0:
            raise TraceContractError(prefix + ".seq is negative")
        if "change_id" not in head or head["seq"] > 0 and not head.get("change_id"):
            missing.append(prefix + ".change_id")
        elif head.get("change_id") is not None and not isinstance(head["change_id"], str):
            raise TraceContractError(prefix + ".change_id must be a string or null")
        elif head["seq"] == 0 and head.get("change_id") is not None:
            raise TraceContractError(prefix + ": empty history has no change id")


def contract_provenance(runtime_stamp=None, provenance=None, *, pack=None, has_checks=False):
    """The runtime stamps and declared provenance of one attempt, from what the caller supplied only.

    Nothing about the selected model, encoder or realizer is read from the host: a leaf the caller did not
    supply stays null and is named in ``missing``. Returns ``base`` (runtime of every event), ``first``
    (runtime of the input event), ``status``, ``missing``, ``declared`` (the caller's sections, exactly).
    """
    partial = ()
    if isinstance(provenance, dict) and "partial_sections" in provenance:
        partial = provenance["partial_sections"]
        if not isinstance(partial, list) or len(partial) > 6:
            raise TraceContractError("provenance.partial_sections must be a list of section names")
        for item in partial:
            if not isinstance(item, str) or len(item) > 13 or item not in SECTIONS or SECTIONS[item] is not list:
                raise TraceContractError("provenance.partial_sections has an invalid section name")
        if len(set(partial)) != len(partial):
            raise TraceContractError("provenance.partial_sections must be unique")
    supplied = plain_json(runtime_stamp, "runtime_stamp") if runtime_stamp is not None else {}
    declared = plain_json(provenance, "provenance") if provenance is not None else {}
    if not isinstance(supplied, dict) or not isinstance(declared, dict):
        raise TraceContractError("runtime_stamp and provenance must be objects")
    selected, missing = {}, []
    for group, names in SELECTED:
        data = supplied.get(group)
        if data is not None and not isinstance(data, dict):
            raise TraceContractError("runtime_stamp.%s must be an object" % group)
        selected[group] = dict(data or {})
        for name in names:
            leaf = (data or {}).get(name)
            if leaf is not None and (not isinstance(leaf, str) or not leaf):
                raise TraceContractError("runtime_stamp.%s.%s must be a non-empty string" % (group, name))
            selected[group][name] = leaf
            if leaf is None:
                missing.append("selected.%s.%s" % (group, name))
    for name, kind in SECTIONS.items():
        if declared.get(name) is not None and not isinstance(declared[name], kind):
            raise TraceContractError("provenance.%s must be a %s" % (name, kind.__name__))
        if name == "criterion":
            criterion = declared.get(name)
            if criterion is None:
                if has_checks:
                    missing.append("provenance.criterion")
                continue
            # A supplied criterion is validated even when no check needs it; only gaps depend on has_checks.
            if criterion.get("id") is not None and not isinstance(criterion["id"], str):
                raise TraceContractError("provenance.criterion.id must be a string")
            if criterion.get("scope") is not None and not isinstance(criterion["scope"], (str, dict)):
                raise TraceContractError("provenance.criterion.scope must be a string or object")
            if has_checks:
                for key in CRITERION_KEYS:
                    if criterion.get(key) in (None, "", {}, []):
                        missing.append("provenance.criterion." + key)
            continue
        if declared.get(name) is None:
            missing.append("provenance.%s" % name)
        elif name in ROW_FIELDS:
            _row_gaps(name, declared[name], missing)
        elif name == "installed_memory_head":
            _head_gaps(declared[name], "provenance.installed_memory_head", missing)
    for name in SECTIONS:
        if name in partial:
            missing.append("provenance.%s.coverage" % name)
    for key in ("build", "pack"):
        if supplied.get(key) is not None and not isinstance(supplied[key], str):
            raise TraceContractError("runtime_stamp.%s must be a string" % key)
    status = INCOMPLETE if missing else COMPLETE
    base = {"build": supplied.get("build") or build(), "pack": supplied.get("pack") or pack,
            "provenance_status": status}
    first = {**base, "pack_digest": supplied.get("pack_digest"),
             "model_digest": selected["model"]["content_fingerprint"],
             "encoder": selected["encoder"]["reference"], "realizer": selected["realizer"]["reference"],
             "selected": selected, "provenance_missing": list(missing),
             "declared_runtime": supplied,
             "replay_status": supplied.get("replay_status")}
    return {"base": base, "first": first, "status": status, "missing": missing, "declared": declared}
