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


# --- delta operations and tombstones -------------------------------------------------------

def _state(store, kind, target_id, at=None):
    item = store.item(kind, target_id, at)
    return item["state"] if item else "none"


def _live_view(store, at=None):
    """Every target's state columns at ``at``, without revision and origin."""
    out = {}
    for kind, table, key in (("node", "cur_nodes", "node_id"), ("edge", "cur_edges", "edge_id"),
                             ("rule", "cur_rules", "rule_id")):
        for (target,) in store._read("SELECT DISTINCT %s FROM %s" % (key, table)):
            item = store.item(kind, target, at)
            if item and item["state"] != "none":
                out[(kind, target)] = {k: v for k, v in item.items() if k not in ("revision", "origin")}
    return out


def test_every_operation(tmp_path):
    store = _new(tmp_path)
    a, b = ids.node_id(G, "a"), ids.node_id(G, "b")
    ab = ids.edge_id(G, "a", "is", "b")
    store.commit([overlay.add_node(G, "a", revision=0, data={"label": "A"}), overlay.add_node(G, "b", revision=0),
                  overlay.add_edge(G, "a", "is", "b", revision=0)], **WHO)
    assert [_state(store, "node", a), _state(store, "node", b), _state(store, "edge", ab)] == ["added"] * 3
    assert store.item("node", a)["data"] == {"label": "A"}

    store.commit([overlay.add_rule("rule:new", {"if": "x", "then": "y"}, revision=0, graph=G)], **WHO)
    rule = store.item("rule", "rule:new")
    assert (rule["state"], rule["body"], rule["graph_id"]) == ("added", {"if": "x", "then": "y"}, G)

    store.commit([overlay.replace_rule("rule:base-7", {"if": "p", "then": "q"}, revision=0)], **WHO)
    rule = store.item("rule", "rule:base-7")
    assert (rule["state"], rule["body"]) == ("replaced", {"if": "p", "then": "q"})
    store.commit([overlay.replace_rule("rule:new", {"if": "x", "then": "z"}, revision=1)], **WHO)
    assert store.item("rule", "rule:new")["state"] == "added"
    assert store.item("rule", "rule:new")["body"] == {"if": "x", "then": "z"}

    store.commit([overlay.disable_rule("rule:base-7", revision=1), overlay.disable_rule("rule:base-9", revision=0)],
                 **WHO)
    assert _state(store, "rule", "rule:base-7") == "disabled"
    assert _state(store, "rule", "rule:base-9") == "disabled"
    with pytest.raises(OverlayError):
        store.commit([overlay.replace_rule("rule:base-9", {}, revision=1)], **WHO)
    with pytest.raises(OverlayError):
        store.commit([overlay.disable_rule("rule:base-9", revision=1)], **WHO)
    with pytest.raises(OverlayError):
        store.commit([overlay.add_rule("rule:new", {}, revision=2)], **WHO)
    store.commit([overlay.add_rule("rule:base-9", {"again": True}, revision=1)], **WHO)
    assert _state(store, "rule", "rule:base-9") == "added"

    store.commit([overlay.retract_edge(G, "a", "is", "b", revision=1)], **WHO)
    assert _state(store, "edge", ab) == "tombstoned"
    base_edge = ids.edge_id(G, "m", "near", "n")
    store.commit([overlay.retract_edge(G, "m", "near", "n", revision=0)], **WHO)
    assert _state(store, "edge", base_edge) == "tombstoned"
    with pytest.raises(OverlayError):
        store.commit([overlay.retract_edge(G, "m", "near", "n", revision=1)], **WHO)
    with pytest.raises(OverlayError):
        store.commit([overlay.add_node(G, "a", revision=1)], **WHO)

    store.commit([overlay.retract_node(G, "b", revision=1)], **WHO)
    assert _state(store, "node", b) == "tombstoned"
    with pytest.raises(OverlayError):
        store.commit([overlay.add_edge(G, "a", "is", "b", revision=2)], **WHO)
    with pytest.raises(OverlayError):
        store.commit([{"op": "RESTORE", "target_kind": "node", "target_id": a, "graph_id": G,
                       "payload": {"fields": {}}, "revision": 1}], **WHO)
    assert store.rebuild()["matched"]


def test_retract_node_tombstones_its_edges_in_the_same_change(tmp_path):
    store = _new(tmp_path)
    store.commit([overlay.add_node(G, n, revision=0) for n in ("a", "b", "c")]
                 + [overlay.add_edge(G, "a", "is", "b", revision=0), overlay.add_edge(G, "c", "likes", "a", revision=0),
                    overlay.add_edge(G, "b", "is", "c", revision=0), overlay.add_edge(G, "a", "self", "a", revision=0)],
                 **WHO)
    store.commit([overlay.retract_edge(G, "a", "old", "x", revision=0)], **WHO)
    with pytest.raises(OverlayError):
        overlay.retract_node(G, "a", revision=1, base_edges=[("y", "near", "z")])
    seq, _ = store.commit([overlay.retract_node(G, "a", revision=1,
                                                base_edges=[("a", "part_of", "z"), ("a", "is", "b"),
                                                            ("a", "old", "x")])], **WHO)
    deltas = store._read("SELECT op, target_id FROM deltas WHERE seq = ? ORDER BY ord", (seq,))
    ops = [(r["op"], r["target_id"]) for r in deltas]
    expected_edges = {ids.edge_id(G, "a", "is", "b"), ids.edge_id(G, "c", "likes", "a"),
                      ids.edge_id(G, "a", "self", "a"), ids.edge_id(G, "a", "part_of", "z")}
    assert ops[-1] == ("RETRACT_NODE", ids.node_id(G, "a"))
    assert [op for op, _ in ops[:-1]] == ["RETRACT_EDGE"] * 4
    assert {t for _, t in ops[:-1]} == expected_edges
    for edge in expected_edges:
        assert _state(store, "edge", edge) == "tombstoned"
        assert store.item("edge", edge)["origin"]["seq"] == seq
    assert _state(store, "edge", ids.edge_id(G, "b", "is", "c")) == "added"
    assert store.item("edge", ids.edge_id(G, "a", "old", "x"))["origin"]["seq"] == 2
    assert store.rebuild()["matched"]


def test_stale_revision_refused(tmp_path):
    store = _new(tmp_path)
    store.commit([overlay.add_node(G, "a", revision=0)], **WHO)
    with pytest.raises(overlay.OverlayStaleRevision):
        store.commit([overlay.retract_node(G, "a", revision=0)], **WHO)
    with pytest.raises(overlay.OverlayStaleRevision):
        store.commit([overlay.add_node(G, "b", revision=0), overlay.add_node(G, "a", revision=5)], **WHO)
    assert store.head()[0] == 1
    assert store.item("node", ids.node_id(G, "b")) is None
    store.commit([overlay.retract_node(G, "a", revision=1)], **WHO)
    assert store.item("node", ids.node_id(G, "a"))["revision"] == 2


def test_undo_keeps_history_and_restores_the_state(tmp_path):
    store = _new(tmp_path)
    first, _ = store.commit([overlay.add_node(G, "a", revision=0, data={"v": 1}), overlay.add_node(G, "b", revision=0),
                             overlay.add_edge(G, "a", "is", "b", revision=0, data={"w": 2}),
                             overlay.replace_rule("rule:r", {"v": 1}, revision=0)], **WHO)
    before = _live_view(store)
    retract, retract_id = store.commit([overlay.retract_node(G, "a", revision=1, base_edges=[("a", "near", "z")]),
                                        overlay.disable_rule("rule:r", revision=1)], **WHO)
    assert _state(store, "node", ids.node_id(G, "a")) == "tombstoned"
    undo, _ = store.undo(retract_id, actor="owner", source="test", reason="undo the retraction", approved_by="owner")
    assert (retract, undo) == (2, 3)
    assert [r["seq"] for r in store._read("SELECT seq FROM changes ORDER BY seq")] == [1, 2, 3]
    assert _live_view(store) == before
    assert _live_view(store, at=retract) != before
    assert store.item("edge", ids.edge_id(G, "a", "near", "z"))["state"] == "none"
    with pytest.raises(overlay.OverlayStaleRevision):
        store.undo(retract, actor="owner", source="test", reason="again", approved_by="owner")
    store.undo(undo, actor="owner", source="test", reason="redo", approved_by="owner")
    assert _live_view(store) == _live_view(store, at=retract)
    with pytest.raises(overlay.OverlayStaleRevision):
        store.undo(first, actor="owner", source="test", reason="too far back", approved_by="owner")
    assert store.head()[0] == 4
    assert store.rebuild()["matched"]


def test_retract_then_readd_gives_the_same_edge_id(tmp_path):
    store = _new(tmp_path)
    edge = ids.edge_id(G, "a", "is", "b")
    store.commit([overlay.add_edge(G, "a", "is", "b", revision=0, data={"n": 1})], **WHO)
    store.commit([overlay.retract_edge(G, "a", "is", "b", revision=1)], **WHO)
    readd = overlay.add_edge(G, "a", "is", "b", revision=2, data={"n": 2})
    assert readd["target_id"] == edge
    store.commit([readd], **WHO)
    item = store.item("edge", edge)
    assert (item["id"], item["state"], item["revision"], item["data"]) == (edge, "added", 3, {"n": 2})
    assert store._read("SELECT COUNT(DISTINCT edge_id) FROM cur_edges")[0][0] == 1
