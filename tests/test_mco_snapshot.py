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
from marco.storage import conversations, overlay, snapshot
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


# --- restoring, with checks ---------------------------------------------------------------------

NEXT = ("지금 지연 구슬은 몇 개야?", "지연이 민수에게 베풀었다.", "지금 민수 구슬은 몇 개야?")


def _outcomes(context, questions=NEXT):
    """Answer, status and evidence (transitions, verification, meaning) as JSON data."""
    out = []
    for text in questions:
        outcome = context.turn(text, KG)
        out.append(json.loads(json.dumps(outcome, ensure_ascii=False, sort_keys=True)))
    return out


def _resign(path, change):
    """Rewrite a snapshot's body with ``change`` and a correct header: damage only in meaning."""
    header, _, body = path.read_bytes().partition(b"\n")
    value = json.loads(body)
    change(value)
    data = snapshot.canonical(value)
    path.write_bytes(b"MARCO-SNAPSHOT/1 %d %s\n" % (len(data), snapshot._sha(data).encode()) + data)


def test_restore_in_another_process_answers_with_the_same_evidence(tmp_path):
    import subprocess
    import sys
    import textwrap
    context = _context()
    target = tmp_path / "chat.snap"
    snapshot.write(target, base=BASE, conversations=[_record(context)])
    expected = _outcomes(context)
    script = textwrap.dedent("""
        import json, sys
        from marco.reasoning.context import ReasoningContext
        from marco.storage import snapshot
        snap = snapshot.read(sys.argv[1])
        status, records = snap.restore_states(json.loads(sys.argv[2]))
        context = ReasoningContext()
        context.restore(records[0]["reasoning_state"])
        out = [context.turn(text, "graphs/graph_일상추론.kg") for text in json.loads(sys.argv[3])]
        print(json.dumps({"status": status, "out": out}, ensure_ascii=False, sort_keys=True))
    """)
    env = dict(os.environ, PYTHONPATH=str(ROOT), NAI_LANGUAGE="한국어", KG_ENCODER="문자")
    done = subprocess.run([sys.executable, "-c", script, str(target), json.dumps(BASE),
                           json.dumps(NEXT, ensure_ascii=False)],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["status"] == "same"
    assert result["out"] == expected
    assert [o["answer"] for o in expected][::2] == ["5개입니다.", "8개입니다."]


def test_restore_uses_the_saved_replay_when_nothing_changed(tmp_path, monkeypatch):
    context = _context()
    data = snapshot.build(base=BASE, conversations=[_record(context)])
    status, records = snapshot.loads(data).restore_states(BASE)
    assert status == "same" and "replay" in records[0]["reasoning_state"]
    restored = ReasoningContext()
    restored.restore(records[0]["reasoning_state"])
    parser = restored._parser()
    original = parser.parse

    def parse_only_new(text, *args, **kwargs):
        if text in HISTORY:
            raise AssertionError("a restored history must use the saved replay record")
        return original(text, *args, **kwargs)

    monkeypatch.setattr(parser, "parse", parse_only_new)
    assert restored.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "5개입니다."


def test_another_base_is_refused(tmp_path):
    snap = snapshot.loads(snapshot.build(base=BASE, conversations=[_record(_context())]))
    with pytest.raises(snapshot.SnapshotBaseMismatch):
        snap.restore_states(dict(BASE, content_sha256="cd" * 32))
    with pytest.raises(snapshot.SnapshotBaseMismatch):
        snap.restore_states(dict(BASE, build_id="build-2"))
    # A base without a build id is compared by content alone.
    assert snap.restore_states(dict(BASE, build_id=None))[0] == "same"


def test_another_overlay_history_is_refused(tmp_path):
    store = _overlay(tmp_path, changes=2)
    store.close()
    snap = snapshot.loads(snapshot.build(base=BASE, conversations=[_record(_context())],
                                         overlay=tmp_path / "base.overlay"))
    assert snap.restore_states(BASE, tmp_path / "base.overlay")[0] == "same"
    # Another overlay of the same base with as many changes: other change ids at the seq.
    _overlay(tmp_path, name="other.overlay", changes=2).close()
    with pytest.raises(snapshot.SnapshotOverlayMismatch):
        snap.restore_states(BASE, tmp_path / "other.overlay")
    # Shorter than the recorded seq.
    _overlay(tmp_path, name="short.overlay", changes=1).close()
    with pytest.raises(snapshot.SnapshotOverlayMismatch):
        snap.restore_states(BASE, tmp_path / "short.overlay")
    # Bound to another base, or missing.
    _overlay(tmp_path, name="foreign.overlay", changes=2, base="cd" * 32).close()
    with pytest.raises(snapshot.SnapshotOverlayMismatch):
        snap.restore_states(BASE, tmp_path / "foreign.overlay")
    with pytest.raises(snapshot.SnapshotOverlayMismatch):
        snap.restore_states(BASE, None)
    with pytest.raises(snapshot.SnapshotOverlayMismatch):
        snap.restore_states(BASE, tmp_path / "absent.overlay")


def test_an_overlay_that_moved_on_drops_the_saved_replay(tmp_path):
    store = _overlay(tmp_path, changes=1)
    snap = snapshot.loads(snapshot.build(base=BASE, conversations=[_record(_context())],
                                         overlay=tmp_path / "base.overlay"))
    store.commit([overlay.add_node("graphs/x.kg", "later", revision=0)], **WHO)
    status, records = snap.restore_states(BASE, store)
    store.close()
    assert status == "advanced" and "replay" not in records[0]["reasoning_state"]
    restored = ReasoningContext()
    restored.restore(records[0]["reasoning_state"])          # re-derived from the observations
    assert restored.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "5개입니다."
    # Without an overlay at the time of the snapshot, any later overlay of the base is "advanced".
    plain = snapshot.loads(snapshot.build(base=BASE, conversations=[]))
    assert plain.check_overlay(tmp_path / "base.overlay") == "advanced"


def test_damaged_truncated_or_unknown_snapshots_are_refused(tmp_path):
    target = tmp_path / "s.snap"
    snapshot.write(target, base=BASE, conversations=[_record(_context())])
    data = target.read_bytes()
    damaged = {
        "truncated": data[:-1],
        "cut in the header": data[:10],
        "empty": b"",
        "extended": data + b" ",
        "one byte flipped": data[:-40] + bytes([data[-40] ^ 1]) + data[-39:],
        "not a snapshot": b"{}",
    }
    for name, value in damaged.items():
        (tmp_path / "bad.snap").write_bytes(value)
        with pytest.raises(snapshot.SnapshotDamaged):
            snapshot.read(tmp_path / "bad.snap")
    unknown = {
        "state schema": lambda v: v["conversations"][0]["reasoning_state"].update(schema="reasoning-context-v99"),
        "contract schema": lambda v: v["contract"]["schemas"].append("persona-v1"),
        "feature": lambda v: v["contract"]["requires"].append("consolidation/1"),
        "version": lambda v: v.update(version=2),
    }
    for change in unknown.values():
        target.write_bytes(data)
        _resign(target, change)
        with pytest.raises(snapshot.SnapshotUnsupported):
            snapshot.read(target)
    target.write_bytes(data)
    _resign(target, lambda v: v["base"].update(content_sha256="xyz"))
    with pytest.raises(snapshot.SnapshotDamaged):
        snapshot.read(target)
    # The overlay copy is checked against its own size and digest before it is used.
    store = _overlay(tmp_path, changes=1)
    store.close()
    snapshot.write(target, base=BASE, conversations=[], overlay=tmp_path / "base.overlay")
    _resign(target, lambda v: v["overlay"]["copy"].update(sha256="0" * 64))
    with pytest.raises(snapshot.SnapshotDamaged):
        snapshot.read(target).extract_overlay(tmp_path / "copy.overlay")
    assert not (tmp_path / "copy.overlay").exists()


# --- the conversation store's envelope -----------------------------------------------------------

def _bound(path, seq=None, change_id=None, content=BASE["content_sha256"], build="build-1"):
    return conversations.ConversationStore(path, conversations.binding(content, build, seq, change_id))


def _saved_chat(store, context):
    chat = store.create_chat()["id"]
    store.append_turn(chat, HISTORY[-1], "기억했습니다.", "answer", reasoning_state=context.snapshot())
    return chat


def test_store_records_the_binding_and_restores_as_today_when_it_matches(tmp_path):
    path = tmp_path / "conversations.json"
    context = _context()
    chat = _saved_chat(_bound(path, 3, "chg_3"), context)
    saved = json.loads(path.read_text(encoding="utf-8"))["chats"][0]
    assert saved["reasoning_binding"] == {"base": {"content_sha256": BASE["content_sha256"], "build_id": "build-1"},
                                          "overlay": {"seq": 3, "change_id": "chg_3"}}
    state = _bound(path, 3, "chg_3").reasoning_state(chat)
    assert state == json.loads(json.dumps(context.snapshot(), ensure_ascii=False)) and "replay" in state


def test_store_drops_the_replay_when_the_overlay_moved(tmp_path):
    path = tmp_path / "conversations.json"
    chat = _saved_chat(_bound(path), _context())
    for store in (_bound(path, 1, "chg_1"), conversations.ConversationStore(path, conversations.binding(
            BASE["content_sha256"], None, 1, "chg_1"))):
        state = store.reasoning_state(chat)
        assert "replay" not in state and state["observations"] == list(HISTORY)
        restored = ReasoningContext()
        restored.restore(state)
        assert restored.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "5개입니다."


def test_store_refuses_a_state_saved_on_another_base_and_keeps_the_turns(tmp_path):
    path = tmp_path / "conversations.json"
    chat = _saved_chat(_bound(path), _context())
    for other in (_bound(path, content="cd" * 32), _bound(path, build="build-2")):
        with pytest.raises(conversations.ConversationBaseMismatch, match="refused, the turns stay readable"):
            other.reasoning_state(chat)
        assert [t["user"] for t in other.get_chat(chat)["turns"]] == [HISTORY[-1]]
        assert other.overview()["general_chats"][0]["id"] == chat


def test_store_without_an_envelope_loads_as_before(tmp_path):
    path = tmp_path / "conversations.json"
    context = _context()
    chat = _saved_chat(conversations.ConversationStore(path), context)   # an unbound store: no envelope
    assert "reasoning_binding" not in json.loads(path.read_text(encoding="utf-8"))["chats"][0]
    expected = json.loads(json.dumps(context.snapshot(), ensure_ascii=False))
    assert _bound(path, 5, "chg_5").reasoning_state(chat) == expected
    # A bound file read by an unbound store (the UI today) also loads as before.
    bound = tmp_path / "bound.json"
    chat = _saved_chat(_bound(bound), context)
    assert conversations.ConversationStore(bound).reasoning_state(chat) == expected
    # A newer state saved by an unbound store does not keep the older binding.
    store = conversations.ConversationStore(bound)
    store.append_turn(chat, "지금 지연 구슬은 몇 개야?", "5개입니다.", "answer", reasoning_state=context.snapshot())
    assert store.reasoning_binding(chat) is None


def test_store_writes_through_a_unique_synced_temp_file(tmp_path, monkeypatch):
    path = tmp_path / "conversations.json"
    store = conversations.ConversationStore(path)
    replaced, synced = [], []
    real_replace, real_fsync = os.replace, os.fsync
    monkeypatch.setattr(os, "replace", lambda a, b: (replaced.append((str(a), str(b))), real_replace(a, b))[1])
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd))[1])
    store.create_chat()
    store.create_chat()
    assert len(replaced) == 2 and len(synced) >= 2
    temps = [a for a, _ in replaced]
    assert len(set(temps)) == 2 and all(str(os.getpid()) in t for t in temps)
    assert str(path.with_suffix(".tmp")) not in temps and all(b == str(path) for _, b in replaced)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["conversations.json"]


def test_store_imports_a_snapshot_chat_under_its_binding(tmp_path):
    context = _context()
    record = snapshot.loads(snapshot.build(base=BASE, conversations=[_record(context)])).conversation()
    store = _bound(tmp_path / "conversations.json")
    chat = store.import_chat(record)
    assert chat["id"] == "chat-1" and [t["user"] for t in chat["turns"]] == list(HISTORY)
    assert store.reasoning_binding("chat-1") == store.binding
    assert store.reasoning_state("chat-1") == record["reasoning_state"]
    with pytest.raises(ValueError):
        store.import_chat(record)


# --- the mco surface: Session.snapshot, mco.load(snapshot=...), mco snapshot, mco inspect ----------

SPECS = {
    "ko": {"graphs": ["graphs/graph_정산_나눠내기.kg", "graphs/graph_일상추론.kg"], "language": "styles/한국어.json"},
    "en": {"graphs": ["graphs/graph_en_bill_split.kg", "graphs/graph_일상추론.kg"], "language": "styles/english.json"},
}
DIALOGUES = {
    "ko": (["돌은 23개 있다.", "돌 8개를 꺼냈다."],
           ["지금 돌은 몇 개야?", "돌 2개를 넣었다.", "지금 돌은 몇 개야?"], ["15개입니다.", None, "17개입니다."]),
    "en": (["Minsu has five apples.", "Minsu ate two apples."],
           ["How many apples does Minsu have?", "Minsu bought four apples.", "How many apples does Minsu have?"],
           ["3 apples.", None, "7 apples."]),
}


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    import mco
    out = tmp_path_factory.mktemp("snapshot-models")
    paths = {}
    for lang, spec in SPECS.items():
        paths[lang] = out / f"{lang}.mco"
        mco.compile(ROOT, paths[lang], name=f"S-{lang}", format="native", **spec)
    paths["ko-compat"] = out / "ko-compat.mco"
    mco.compile(ROOT, paths["ko-compat"], name="S-ko", format="compat", **SPECS["ko"])
    return paths


def _dump(result):
    return {"answer": result.answer, "status": result.status.value,
            "evidence": [e.to_dict() for e in result.evidence]}


def _resume_elsewhere(model, snap, questions, language):
    """Load ``model`` with ``snap`` in a fresh interpreter and ask ``questions`` there."""
    import subprocess
    import sys
    code = ("import json, sys, mco\n"
            "with mco.load(sys.argv[1], snapshot=sys.argv[2]) as m:\n"
            "    out = [m.run(q) for q in json.loads(sys.argv[3])]\n"
            "print(json.dumps([{'answer': r.answer, 'status': r.status.value,\n"
            "                   'evidence': [e.to_dict() for e in r.evidence]} for r in out], ensure_ascii=False))\n")
    env = dict(os.environ, PYTHONPATH=str(ROOT), NAI_LANGUAGE=language, KG_ENCODER="문자")
    done = subprocess.run([sys.executable, "-c", code, str(model), str(snap), json.dumps(questions, ensure_ascii=False)],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout)


@pytest.mark.parametrize("lang", [pytest.param("ko", marks=pytest.mark.language("한국어")),
                                  pytest.param("en", marks=pytest.mark.language("english"))])
def test_session_snapshot_resumes_in_a_new_process_and_answers_as_without_the_restart(models, tmp_path, lang):
    import mco
    turns, questions, answers = DIALOGUES[lang]
    with mco.load(models[lang]) as model:
        session = model.session()
        for text in turns:
            session.run(text)
        info = session.snapshot(tmp_path / "a.snap")
        again = session.snapshot(tmp_path / "b.snap")
        assert (tmp_path / "a.snap").read_bytes() == (tmp_path / "b.snap").read_bytes()   # same state, same bytes
        assert info.sha256 == again.sha256 and info.conversations == 1 and info.turns == len(turns)
        assert info.base["content_sha256"] == model.info.manifest["mco"]["content_sha256"]
        assert info.base["build_id"] == model.info.build_id and info.overlay is None
        assert "reasoning-context-v10" in info.schemas
        assert model.info.supports(mco.Capability.SNAPSHOT)
        expected = [_dump(session.run(q)) for q in questions]          # the same process, no restart
    assert [e["answer"] for e in expected][0::2] == [a for a in answers if a]
    assert expected[0]["evidence"], expected[0]
    assert _resume_elsewhere(models[lang], tmp_path / "a.snap", questions,
                             "한국어" if lang == "ko" else "english") == expected


def test_resume_in_process_and_its_refusals(models, tmp_path):
    import mco
    turns, questions, answers = DIALOGUES["ko"]
    with mco.load(models["ko"]) as model:
        session = model.session()
        for text in turns:
            session.run(text)
        session.snapshot(tmp_path / "ko.snap")
        resumed = model.resume(tmp_path / "ko.snap")
        assert resumed.run(questions[0]).answer == answers[0]
        # The session that wrote it goes on independently.
        session.run("돌 10개를 꺼냈다.")
        assert resumed.run(questions[0]).answer == answers[0]
    # The same content in the compat container is the same base.
    with mco.load(models["ko-compat"], snapshot=tmp_path / "ko.snap") as compat:
        assert compat.run(questions[0]).answer == answers[0]
    # Another base: refused, whether through load or resume.
    with pytest.raises(mco.SnapshotMismatchError):
        mco.load(models["en"], snapshot=tmp_path / "ko.snap")
    # A damaged or truncated file: refused.
    data = (tmp_path / "ko.snap").read_bytes()
    (tmp_path / "cut.snap").write_bytes(data[:-5])
    with mco.load(models["ko"]) as model:
        with pytest.raises(mco.SnapshotFormatError):
            model.resume(tmp_path / "cut.snap")
        with pytest.raises(mco.SnapshotError):
            model.resume(tmp_path / "absent.snap")
        # A fresh session's snapshot holds one empty conversation.
        empty = model.session().snapshot(tmp_path / "empty.snap")
        assert (empty.conversations, empty.turns) == (1, 0)


def test_cli_snapshot_inspect_and_resume(models, tmp_path):
    import io
    import subprocess
    import sys
    import mco
    from mco.cli import main
    turns, questions, answers = DIALOGUES["ko"]
    target = tmp_path / "cli.snap"
    out = io.StringIO()
    assert main(["snapshot", str(models["ko"]), *turns, "-o", str(target), "--json"], stdout=out) == 0
    written = json.loads(out.getvalue())
    assert len(written["results"]) == 2 and written["snapshot"]["turns"] == 2
    out = io.StringIO()
    assert main(["inspect", str(target), "--json"], stdout=out) == 0
    described = json.loads(out.getvalue())
    content = mco.inspect(models["ko"]).to_dict(include_manifest=True)["manifest"]["mco"]["content_sha256"]
    assert described["base"]["content_sha256"] == content and described["overlay"] is None
    assert described["conversations"] == 1 and "reasoning-context-v10" in described["schemas"]
    out = io.StringIO()
    assert main(["inspect", str(target)], stdout=out) == 0
    text = out.getvalue()
    assert "marco-snapshot v1" in text and content in text and "none attached" in text and "conversations" in text
    out = io.StringIO()
    assert main(["run", str(models["ko"]), "--resume", str(target), questions[0]], stdout=out) == 0
    assert out.getvalue().startswith(answers[0])
    # Continue the snapshot and write a new one.
    assert main(["snapshot", str(models["ko"]), "--resume", str(target), "돌 2개를 넣었다.",
                 "-o", str(tmp_path / "next.snap")], stdout=io.StringIO()) == 0
    assert mco.inspect_snapshot(tmp_path / "next.snap").turns == 3
    # Inspecting runs nothing: no engine module is imported.
    code = ("import sys, mco; info = mco.inspect_snapshot(sys.argv[1]); "
            "leaked = [m for m in ('engine', 'pack_model', 'views.kgpack_ui', 'marco.reasoning.context') "
            "if m in sys.modules]; print(info.conversations, leaked)")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    done = subprocess.run([sys.executable, "-c", code, str(target)], cwd=ROOT, env=env,
                          capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "1 []"
