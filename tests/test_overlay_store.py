"""The overlay store of the Persistent Overlay Infrastructure (docs/architecture/overlay.md):
stable ids, a store bound to one base, one transaction per change, append-only history,
one writer, derived state that a rebuild reproduces."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap
import time
import unicodedata

import pytest

from marco.storage import ids, overlay
from marco.storage.overlay import (OverlayBaseMismatch, OverlayConflict, OverlayError, OverlayStore,
                                   OverlayWriterBusy)

ROOT = Path(__file__).resolve().parents[1]
BASE = "ab" * 32
OTHER = "cd" * 32
G = "graphs/x.kg"
WHO = dict(actor="owner", source="test", reason="stated in the test", approved_by="owner")


def _new(tmp_path, name="base.mco.overlay"):
    return OverlayStore.create(tmp_path / name, base_sha256=BASE, base_build_id="build-1", format_version=1)


def _run(script, *args):
    """Run ``script`` in a fresh interpreter at the repository root; returns the completed process."""
    return subprocess.run([sys.executable, "-c", textwrap.dedent(script)] + [str(a) for a in args],
                          cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)),
                          capture_output=True, text=True, timeout=120)


# --- ids ---------------------------------------------------------------------------------

def test_ids_fixed_values():
    assert ids.graph_id("graphs\\sub\\y.kg") == "graphs/sub/y.kg"
    assert ids.node_id(G, "a") == "graphs/x.kg#a"
    assert ids.edge_id(G, "a", "is", "b") == "e:ad915d5e1daca67813991cca8c86fef2"
    assert ids.edge_id("graphs/사람.kg", "철수", "친구", "영희") == "e:26924db0004b2a70ae2de12c9fa26366"
    assert ids.rule_id("rule:transfer-1") == "rule:transfer-1"


def test_ids_are_nfc():
    nfd = lambda s: unicodedata.normalize("NFD", s)
    assert ids.graph_id(nfd("graphs/사람.kg")) == "graphs/사람.kg"
    assert ids.node_id(nfd("graphs/사람.kg"), nfd("영희")) == "graphs/사람.kg#영희"
    assert ids.edge_id(nfd("graphs/사람.kg"), nfd("철수"), "친구", nfd("영희")) == "e:26924db0004b2a70ae2de12c9fa26366"
    with pytest.raises(ValueError):
        ids.edge_id(G, "a\x1fb", "is", "c")


# --- binding to the base -----------------------------------------------------------------

def test_base_mismatch_refused(tmp_path):
    store = _new(tmp_path)
    store.commit([overlay.add_node(G, "a", revision=0)], **WHO)
    path = store.path
    store.close()
    with pytest.raises(OverlayBaseMismatch):
        OverlayStore.open(path, base_sha256=OTHER)
    with pytest.raises(OverlayBaseMismatch):
        OverlayStore.open(path, base_sha256=OTHER, writer=True)
    with pytest.raises(OverlayBaseMismatch):
        OverlayStore.open(path, base_sha256=BASE, base_build_id="build-2")
    with OverlayStore.open(path, base_sha256=BASE, base_build_id="build-1") as store:
        assert store.head()[0] == 1
        assert store.meta()["base_sha256"] == BASE
        assert store.meta()["overlay_schema"] == str(overlay.OVERLAY_SCHEMA)


def test_no_overlay_is_created_by_opening(tmp_path):
    missing = tmp_path / "missing.overlay"
    with pytest.raises(OverlayError):
        OverlayStore.open(missing, base_sha256=BASE, writer=True)
    assert not missing.exists()
    _new(tmp_path).close()
    with pytest.raises(OverlayError):
        _new(tmp_path)


def test_a_file_that_is_not_an_overlay_is_refused(tmp_path):
    path = tmp_path / "plain.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    db.commit()
    db.close()
    with pytest.raises(OverlayError):
        OverlayStore.open(path, base_sha256=BASE)


# --- one transaction per change ------------------------------------------------------------

def test_exception_mid_commit_leaves_nothing(tmp_path, monkeypatch):
    store = _new(tmp_path)
    store.commit([overlay.add_node(G, "a", revision=0)], **WHO)
    real = overlay._apply_delta
    calls = []

    def failing(cur, seq, d):
        calls.append(d["target_id"])
        if len(calls) == 2:
            raise RuntimeError("injected failure after the first delta")
        return real(cur, seq, d)

    monkeypatch.setattr(overlay, "_apply_delta", failing)
    with pytest.raises(RuntimeError):
        store.commit([overlay.add_node(G, "b", revision=0), overlay.add_node(G, "c", revision=0)], **WHO)
    monkeypatch.setattr(overlay, "_apply_delta", real)
    assert store.head()[0] == 1
    assert store.item("node", ids.node_id(G, "b")) is None
    assert store.item("node", ids.node_id(G, "c")) is None
    assert store.rebuild()["matched"]
    assert store.commit([overlay.add_node(G, "b", revision=0)], **WHO)[0] == 2


_KILL_MID_COMMIT = """
    import os, signal, sys
    from marco.storage import overlay
    path, base = sys.argv[1], sys.argv[2]
    store = overlay.OverlayStore.open(path, base_sha256=base, writer=True)
    real = overlay._apply_delta
    calls = []
    def dying(cur, seq, d):
        calls.append(1)
        if len(calls) == 3:
            os.kill(os.getpid(), signal.SIGKILL) if hasattr(signal, "SIGKILL") else os._exit(9)
        return real(cur, seq, d)
    overlay._apply_delta = dying
    g = "graphs/x.kg"
    store.commit([overlay.add_node(g, n, revision=0) for n in ("k1", "k2", "k3", "k4")],
                 actor="owner", source="test", reason="r", approved_by="owner")
    print("not killed")
"""


def test_killed_mid_commit_leaves_nothing_and_reopens(tmp_path):
    store = _new(tmp_path)
    store.commit([overlay.add_node(G, "a", revision=0)], **WHO)
    path = store.path
    store.close()
    done = _run(_KILL_MID_COMMIT, path, BASE)
    assert done.returncode != 0 and "not killed" not in done.stdout, done.stderr
    with OverlayStore.open(path, base_sha256=BASE, writer=True) as store:
        assert store.head()[0] == 1
        for name in ("k1", "k2", "k3", "k4"):
            assert store.item("node", ids.node_id(G, name)) is None
        assert store.rebuild()["matched"]
        assert store.commit([overlay.add_node(G, "k1", revision=0)], **WHO)[0] == 2


_KILL_AFTER_COMMIT = """
    import os, signal, sys
    from marco.storage import overlay
    path, base = sys.argv[1], sys.argv[2]
    store = overlay.OverlayStore.open(path, base_sha256=base, writer=True)
    store.commit([overlay.add_node("graphs/x.kg", "after", revision=0)], change_id="chg_fixed",
                 actor="owner", source="test", reason="r", approved_by="owner")
    os.kill(os.getpid(), signal.SIGKILL) if hasattr(signal, "SIGKILL") else os._exit(9)
"""


def test_killed_after_commit_keeps_the_change_and_a_retry_is_a_no_op(tmp_path):
    store = _new(tmp_path)
    path = store.path
    store.close()
    done = _run(_KILL_AFTER_COMMIT, path, BASE)
    assert done.returncode != 0, done.stderr
    with OverlayStore.open(path, base_sha256=BASE, writer=True) as store:
        assert store.head() == (1, "chg_fixed")
        again = store.commit([overlay.add_node(G, "after", revision=0)], change_id="chg_fixed", **WHO)
        assert again == (1, "chg_fixed")
        assert store.head() == (1, "chg_fixed")


def test_reapplying_a_change_id_is_a_no_op(tmp_path):
    store = _new(tmp_path)
    first = store.commit([overlay.add_node(G, "a", revision=0)], change_id="chg_one", **WHO)
    again = store.commit([overlay.add_node(G, "a", revision=0)], change_id="chg_one", **WHO)
    assert first == again == (1, "chg_one")
    assert store.head() == (1, "chg_one")
    assert store.item("node", ids.node_id(G, "a"))["revision"] == 1
    with pytest.raises(OverlayConflict):
        store.commit([overlay.add_node(G, "b", revision=0)], change_id="chg_one", **WHO)
    assert store.head() == (1, "chg_one")


# --- append-only history -------------------------------------------------------------------

def test_update_and_delete_on_history_rejected(tmp_path):
    store = _new(tmp_path)
    store.commit([overlay.add_node(G, "a", revision=0)], **WHO)
    db = sqlite3.connect(store.path, timeout=0)
    for sql in ("UPDATE changes SET actor = 'someone else'", "DELETE FROM changes",
                "UPDATE deltas SET revision = 5", "DELETE FROM deltas",
                "UPDATE meta SET value = 'x' WHERE key = 'base_sha256'", "DELETE FROM meta"):
        with pytest.raises(sqlite3.DatabaseError):
            db.execute(sql)
        db.rollback()
    db.close()
    assert store.head()[0] == 1
    assert store.meta()["base_sha256"] == BASE


# --- one writer ----------------------------------------------------------------------------

_TRY_WRITER = """
    import sys
    from marco.storage import overlay
    try:
        overlay.OverlayStore.open(sys.argv[1], base_sha256=sys.argv[2], writer=True)
    except overlay.OverlayWriterBusy:
        print("refused")
    else:
        print("opened")
"""


def test_second_writer_refused(tmp_path):
    store = _new(tmp_path)
    with pytest.raises(OverlayWriterBusy):
        OverlayStore.open(store.path, base_sha256=BASE, writer=True)
    assert _run(_TRY_WRITER, store.path, BASE).stdout.strip() == "refused"
    with OverlayStore.open(store.path, base_sha256=BASE) as reader:
        assert reader.head() == (0, None)
        with pytest.raises(OverlayError):
            reader.commit([overlay.add_node(G, "a", revision=0)], **WHO)
    store.close()
    assert _run(_TRY_WRITER, store.path, BASE).stdout.strip() == "opened"


def test_a_foreign_write_transaction_refuses_at_once(tmp_path):
    store = _new(tmp_path)
    foreign = sqlite3.connect(store.path, timeout=0, isolation_level=None)
    foreign.execute("BEGIN IMMEDIATE")
    started = time.perf_counter()
    with pytest.raises(OverlayWriterBusy):
        store.commit([overlay.add_node(G, "a", revision=0)], **WHO)
    assert time.perf_counter() - started < 1.0
    foreign.execute("ROLLBACK")
    foreign.close()
    assert store.commit([overlay.add_node(G, "a", revision=0)], **WHO)[0] == 1


# --- derived state -------------------------------------------------------------------------

def test_rebuild_reproduces_the_current_state(tmp_path):
    store = _new(tmp_path)
    store.commit([overlay.add_node(G, "a", revision=0), overlay.add_node(G, "b", revision=0)], **WHO)
    store.commit([overlay.add_edge(G, "a", "is", "b", revision=0, data={"weight": 1})], **WHO)
    report = store.rebuild()
    assert report == {"matched": True, "rows": 3, "changes": 2}
    db = sqlite3.connect(store.path, timeout=5)
    db.execute("DELETE FROM cur_edges")
    db.execute("UPDATE cur_nodes SET data = '\"tampered\"'")
    db.commit()
    db.close()
    assert store.rebuild()["matched"] is False
    assert store.rebuild()["matched"] is True
    edge = store.item("edge", ids.edge_id(G, "a", "is", "b"))
    assert edge["state"] == "added" and edge["data"] == {"weight": 1}
    assert store.item("node", ids.node_id(G, "a"))["data"] is None


def test_a_reader_reads_at_a_pinned_seq(tmp_path):
    store = _new(tmp_path)
    store.commit([overlay.add_node(G, "a", revision=0)], **WHO)
    with OverlayStore.open(store.path, base_sha256=BASE) as reader:
        pinned, _ = reader.head()
        store.commit([overlay.add_node(G, "b", revision=0)], **WHO)
        assert reader.item("node", ids.node_id(G, "b"), at=pinned) is None
        assert reader.item("node", ids.node_id(G, "b"))["origin"]["seq"] == 2
        with pytest.raises(OverlayError):
            reader.item("node", ids.node_id(G, "b"), at=3)
