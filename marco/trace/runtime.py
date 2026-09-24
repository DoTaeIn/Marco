"""Runtime stamp (design note §19, §37): what ran, so a trace can be replayed.

Every event carries the build and the language pack name. The first event of
a trace also carries the pack digest, the model digest, the encoder mode, the
realizer's declaration version and the replay status.

* build: ``MARCO_BUILD`` if set, else ``git rev-parse HEAD`` of this checkout
  (``+dirty`` when tracked files differ), else ``unknown``. Computed once per process.
* pack digest: SHA-256 of the ``.kgpack`` file's bytes. ``views.kgpack_ui.AppState``
  hashes the same bytes for its overlay id (the first 16 hex characters), and
  the dialogue gate builds its packs with ``kgpack.write_pack``, whose zip
  entries carry a frozen timestamp, so the same sources give the same digest.
* model digest: the ``verification.model`` fingerprint the engine reports
  (SHA-256 over the model's source paths and their digests).
* encoder: ``KG_ENCODER``, defaulting to 문자 as ``bench/dialogue_gate.py`` does.
* realizer: the declaration files ``marco/language/realizer/<stem>.json`` and
  ``meaning.json``, by schema id and SHA-256. They carry no version field of
  their own (request L1-2 asks for one).

Only the standard library; files are read, nothing is imported from the engine.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
REALIZER = ROOT / "marco" / "language" / "realizer"
ENCODER_DEFAULT = "문자"

# Components whose output is not a function of the recorded inputs. A turn that
# used one is stamped replay_status = approximate, naming the component.
NONDETERMINISTIC = {
    "web_research": "goal_runtime research reads the open web (the gate stubs it)",
    "realizer_learning": "the realizer learns expressions from user sentences (live learning)",
}

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
                           "meaning_schema": meaning_schema,
                           "meaning_sha256": _sha256_file(meaning)[:16] if meaning.is_file() else None}
    return _cache[key]


def stamp(pack):
    """The fields every event carries."""
    return {"build": build(), "pack": pack}


def first_stamp(pack, *, pack_file=None, model_digest=None, approximate=()):
    """The fields the first event of a trace carries in addition to ``stamp``."""
    out = {"pack_digest": pack_digest(pack_file), "model_digest": model_digest, "encoder": encoder(),
           "realizer": realizer_version(pack_stem(pack)),
           "replay_status": "approximate" if approximate else "exact"}
    if approximate:
        out["approximate"] = sorted(set(approximate))
    return out
