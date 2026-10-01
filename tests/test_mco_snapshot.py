"""Conversation snapshot and restore (docs/architecture/snapshot.md): one self-describing file
that records the base, the overlay sequence, the contract and each conversation's turns and
reasoning state; written atomically, byte-identical for the same state, and checked before use."""
import ast
import json
import os
from pathlib import Path
import threading

import pytest

from marco.reasoning.context import ReasoningContext
from marco.storage import overlay, snapshot
from marco.storage.overlay import OverlayStore

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack

ROOT = Path(__file__).resolve().parents[1]
KG = "graphs/graph_일상추론.kg"
BASE = {"content_sha256": "ab" * 32, "build_id": "build-1", "format": "test", "format_version": "1"}
WHO = dict(actor="owner", source="test", reason="stated in the test", approved_by="owner")
HISTORY = ("베풀다는 상대에게 구슬 2개를 주는 것이다.", "민수 구슬은 8개 있다.",
           "지연 구슬은 3개 있다.", "민수가 지연에게 베풀었다.")


def _context(history=HISTORY):
    context = ReasoningContext()
    for text in history:
        assert context.turn(text, KG)["status"] == "observed"
    return context


def _record(context, history=HISTORY, conversation_id="chat-1"):
    turns = [{"id": "t%d" % i, "at": 1000.0 + i, "user": text, "assistant": "기억했습니다.", "phase": "answer"}
             for i, text in enumerate(history)]
    return {"id": conversation_id, "title": "구슬", "created_at": 1000.0, "updated_at": 1000.0 + len(turns),
            "turns": turns, "reasoning_state": context.snapshot()}


def _overlay(tmp_path, name="base.overlay", changes=1, base=BASE["content_sha256"]):
    store = OverlayStore.create(tmp_path / name, base_sha256=base, base_build_id="build-1", format_version=1)
    for n in range(changes):
        store.commit([overlay.add_node("graphs/x.kg", "n%d" % n, revision=0)], **WHO)
    return store


# --- writing ------------------------------------------------------------------------------

def test_same_state_gives_byte_identical_snapshots(tmp_path):
    context = _context()
    store = _overlay(tmp_path, changes=2)
    head = store.head()
    store.close()
    first, second = tmp_path / "a.snap", tmp_path / "b.snap"
    snapshot.write(first, base=BASE, conversations=[_record(context)], overlay=tmp_path / "base.overlay",
                   runtime="test 1")
    snapshot.write(second, base=BASE, conversations=[_record(context)], overlay=tmp_path / "base.overlay",
                   runtime="test 1")
    assert first.read_bytes() == second.read_bytes()
    # A context restored from the saved state gives the same snapshot again.
    restored = ReasoningContext()
    restored.restore(_record(context)["reasoning_state"])
    assert snapshot.build(base=BASE, conversations=[_record(restored)], overlay=tmp_path / "base.overlay",
                          runtime="test 1") == first.read_bytes()

    snap = snapshot.read(first)
    assert snap.base["content_sha256"] == BASE["content_sha256"] and snap.base["build_id"] == "build-1"
    assert (snap.overlay["seq"], snap.overlay["change_id"]) == head
    assert snap.contract["runtime"] == "test 1"
    assert set(snap.contract["schemas"]) == {"conversation-turns-v1", "reasoning-context-v10"}
    assert set(snap.contract["requires"]) == {"base-binding/1", "conversation-turns/1",
                                              "reasoning-context-state/1", "overlay-sqlite-copy/1"}
    # The reasoning state is the context's own snapshot, unchanged.
    assert snap.conversation()["reasoning_state"] == json.loads(json.dumps(context.snapshot(), ensure_ascii=False))
    assert [t["user"] for t in snap.conversation("chat-1")["turns"]] == list(HISTORY)
    excluded = {x["id"] for x in snap.body["excluded"]}
    assert {"caches", "pending_plans", "persona_state"} <= excluded


def test_no_overlay_is_stated_explicitly(tmp_path):
    data = snapshot.build(base=BASE, conversations=[_record(_context(HISTORY[:2]), HISTORY[:2])])
    snap = snapshot.loads(data)
    assert snap.body["overlay"] == {"attached": False} and snap.overlay is None
    assert "overlay-sqlite-copy/1" not in snap.contract["requires"]


def test_overlay_copy_is_a_consistent_point_in_time_during_a_commit(tmp_path, monkeypatch):
    store = _overlay(tmp_path, changes=1)
    first = store.head()
    store.close()
    path = tmp_path / "base.overlay"
    inside, release = threading.Event(), threading.Event()
    apply = overlay._apply_delta

    def paused(cur, seq, delta):           # the commit stops halfway, inside its transaction
        result = apply(cur, seq, delta)
        inside.set()
        assert release.wait(30)
        return result

    monkeypatch.setattr(overlay, "_apply_delta", paused)
    errors = []

    def writer():
        try:
            with OverlayStore.open(path, base_sha256=BASE["content_sha256"], writer=True) as w:
                w.commit([overlay.add_node("graphs/x.kg", "late", revision=0)], **WHO)
        except BaseException as e:  # pragma: no cover - reported below
            errors.append(e)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        assert inside.wait(30)
        during = snapshot.loads(snapshot.build(base=BASE, conversations=[], overlay=path))
    finally:
        release.set()
        thread.join(30)
    assert not errors
    assert (during.overlay["seq"], during.overlay["change_id"]) == first
    copy = during.extract_overlay(tmp_path / "copy.overlay")
    with OverlayStore.open(copy, base_sha256=BASE["content_sha256"]) as copied:
        assert copied.head() == first
        assert [n["name"] for n in copied.added_nodes()] == ["n0"]
    after = snapshot.loads(snapshot.build(base=BASE, conversations=[], overlay=path))
    assert after.overlay["seq"] == first[0] + 1


def test_written_atomically_and_never_pickled(tmp_path, monkeypatch):
    source = (ROOT / "marco" / "storage" / "snapshot.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"pickle", "marshal", "shelve", "dill", "cloudpickle"}
    target = tmp_path / "s.snap"
    snapshot.write(target, base=BASE, conversations=[_record(_context(HISTORY[:2]), HISTORY[:2])])
    data = target.read_bytes()
    header, _, body = data.partition(b"\n")
    assert header.decode("ascii").startswith("MARCO-SNAPSHOT/1 ")
    assert isinstance(json.loads(body.decode("utf-8")), dict)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s.snap"]       # no temp file left
    # A failure before the replace leaves the old file whole and no temp file behind.
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        snapshot.write(target, base=BASE, conversations=[])
    assert target.read_bytes() == data
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s.snap"]


def test_writer_refuses_what_it_cannot_record(tmp_path):
    with pytest.raises(snapshot.SnapshotError):
        snapshot.build(base={"content_sha256": "not-a-sha"}, conversations=[])
    with pytest.raises(snapshot.SnapshotError):
        snapshot.build(base=BASE, conversations=[{"id": "x", "turns": [], "reasoning_state": {"schema": "other"}}])
    with pytest.raises(snapshot.SnapshotError):
        snapshot.build(base=BASE, conversations=[{"id": "x", "turns": []}, {"id": "x", "turns": []}])
    other = _overlay(tmp_path, base="cd" * 32)
    other.close()
    with pytest.raises(snapshot.SnapshotBaseMismatch):          # an overlay of another base is not recorded
        snapshot.build(base=BASE, conversations=[], overlay=tmp_path / "base.overlay")
