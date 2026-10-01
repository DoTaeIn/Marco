"""The definition index is built safely when several processes start with no cache."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from marco.knowledge.definitions import DefinitionLookup


ROOT = Path(__file__).resolve().parents[1]
ROWS = 30000
BUILDERS = 6

# Each builder imports first and then waits for one line, so all of them enter the
# build at the same moment rather than one after another.
_BUILDER = """
import json, sys
from pathlib import Path
from marco.knowledge.definitions import DefinitionLookup

lookup = DefinitionLookup(Path(sys.argv[1]), Path(sys.argv[2]))
print("ready", flush=True)
sys.stdin.readline()
print(json.dumps(lookup.lookup_term("term 7")), flush=True)
"""


def _write_source(path: Path, rows: int = ROWS) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for number in range(rows):
            handle.write(json.dumps({"말": f"term {number}", "정의": f"Definition {number}."},
                                    ensure_ascii=False) + "\n")


def _leftovers(cache: Path) -> list[str]:
    return sorted(item.name for item in cache.parent.iterdir() if item.name != cache.name)


def test_processes_starting_together_all_build_one_valid_cache(tmp_path):
    source = tmp_path / "definitions.jsonl"
    cache = tmp_path / "index" / "definitions.sqlite"
    _write_source(source)

    builders = [subprocess.Popen([sys.executable, "-c", _BUILDER, str(source), str(cache)],
                                 cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
                for _ in range(BUILDERS)]
    try:
        for builder in builders:
            assert builder.stdout.readline().strip() == "ready", builder.stderr.read()
        for builder in builders:
            builder.stdin.write("\n")
            builder.stdin.flush()
        results = [builder.communicate(timeout=120) for builder in builders]
    finally:
        for builder in builders:
            if builder.poll() is None:
                builder.kill()

    for builder, (out, err) in zip(builders, results):
        assert builder.returncode == 0, err
        assert json.loads(out)["definition"] == "Definition 7.", err

    db = sqlite3.connect(cache)
    try:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT COUNT(*) FROM definitions").fetchone() == (ROWS,)
    finally:
        db.close()
    assert _leftovers(cache) == []


def test_a_failed_build_leaves_no_cache_and_no_temporary_file(tmp_path):
    source = tmp_path / "definitions.jsonl"
    cache = tmp_path / "index" / "definitions.sqlite"
    _write_source(source, rows=3000)
    with source.open("ab") as handle:
        handle.write(b"\xff\xfe not utf-8\n")

    with pytest.raises(UnicodeDecodeError):
        DefinitionLookup(source, cache).lookup_term("term 7")

    assert not cache.exists()
    assert _leftovers(cache) == []


def test_a_finished_cache_is_reused_and_a_newer_source_rebuilds_it(tmp_path):
    source = tmp_path / "definitions.jsonl"
    cache = tmp_path / "index" / "definitions.sqlite"
    _write_source(source, rows=10)
    lookup = DefinitionLookup(source, cache)

    assert lookup.lookup_term("term 7")["definition"] == "Definition 7."
    built = cache.stat().st_ino
    assert lookup.lookup_term("term 3")["definition"] == "Definition 3."
    assert cache.stat().st_ino == built

    _write_source(source, rows=12)
    older = source.stat().st_mtime - 5
    os.utime(cache, (older, older))
    assert lookup.lookup_term("term 11")["definition"] == "Definition 11."
    assert _leftovers(cache) == []
