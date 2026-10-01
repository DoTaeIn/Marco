"""Acceptance of the Persistent Overlay Infrastructure, through natural-language turns.

A small model (one graph, the Korean pack, this checkout's axioms) is compiled to
MCO Format 1 in the test. Every change goes through the mco API with an approver;
every check is the answer and evidence of a turn of ``mco.load(model, overlay=...)``.
Nothing is recompiled or exported after the model is built.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import mco
from mco import overlay as ov
from tests.test_overlay_runtime import G, LANGUAGE, build_source

pytestmark = pytest.mark.language("한국어")
ROOT = Path(__file__).resolve().parents[1]
WHO = dict(approved_by="owner", reason="explicit test change")

LEAVES = "잎이 축 처졌어"                    # answered only through 잎시듦 -증명-> 흙이말랐다
FINGER = "손가락으로 흙을 눌러 봤더니 말랐어"   # answered through the base edge 손가락확인 -증명-> 흙이말랐다
HEIGHTS = "서우는 도아보다 키가 크다. 도아는 라온보다 키가 크다."
WHO_TALLER = "서우와 라온 중 누가 더 커?"      # answered through the rule strict-height-transitivity


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("overlay-acceptance")
    root = build_source(tmp / "src")
    model = tmp / "small.mco"
    mco.compile(root, model, name="small", language=LANGUAGE, format="native")
    other_root = build_source(tmp / "other")
    (other_root / G).write_text((other_root / G).read_text(encoding="utf-8") + "# another\n", encoding="utf-8")
    other = tmp / "other.mco"
    mco.compile(other_root, other, name="other", language=LANGUAGE, format="native")
    return {"model": model, "other": other}


@pytest.fixture
def setup(built, tmp_path, monkeypatch):
    """A fresh overlay; the model's sha256 before; a count of every compile or export from here on."""
    import marco.storage.kgpack as kgpack
    import mco.formats
    import mco.native.pack
    calls = []

    def counted(module, name):
        real = getattr(module, name)
        monkeypatch.setattr(module, name, lambda *a, **k: (calls.append(name), real(*a, **k))[1])
    for module, name in ((kgpack, "write_pack"), (mco.formats, "write_compat"), (mco.formats, "write_native"),
                         (mco.native.pack, "write_model"), (mco.compiler, "compile")):
        counted(module, name)
    path = tmp_path / "small.overlay"
    mco.create_overlay(built["model"], path)
    before = hashlib.sha256(built["model"].read_bytes()).hexdigest()
    yield {"model": built["model"], "other": built["other"], "overlay": path, "compiles": calls}
    assert hashlib.sha256(built["model"].read_bytes()).hexdigest() == before      # the base file never changes
    assert calls == []                                                             # no recompile, no export


def say(session, text):
    result = session.run(text)
    paths = [(e.text, dict(e.detail).get("origin")) for e in result.evidence.of_kind("graph_path")]
    return result, paths


def origin_of(paths, text):
    return next(origin for edge, origin in paths if edge == text)


def test_one_edge_added_then_retracted_changes_the_answer_and_its_evidence(setup):
    with mco.load(setup["model"], overlay=setup["overlay"]) as model, \
            mco.open_overlay(setup["model"], setup["overlay"]) as o:
        session = model.session()
        before, paths = say(session, LEAVES)
        assert before.status is mco.Status.UNKNOWN and paths == []
        added = o.commit([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다")], **WHO)
        after, paths = say(session, LEAVES)
        assert after.status is mco.Status.ANSWERED and "잎시듦" in after.answer and "흙이말랐다" in after.answer
        origin = origin_of(paths, "잎시듦 -증명-> 흙이말랐다")
        assert origin["kind"] == "overlay" and origin["change_id"] == added["change_id"]
        assert origin["approved_by"] == "owner" and origin["seq"] == 1
        assert origin_of(paths, "흙이말랐다 -충족-> 물을준다") is None          # the base edge is as before
        o.commit([ov.retract_edge(G, "잎시듦", "증명", "흙이말랐다")], **WHO)
        retracted, paths = say(session, LEAVES)
        assert retracted.status is mco.Status.UNKNOWN and paths == []
        assert retracted.answer == before.answer


def test_a_disabled_rule_changes_the_next_answer_and_undo_restores_it(setup):
    with mco.load(setup["model"], overlay=setup["overlay"]) as model, \
            mco.open_overlay(setup["model"], setup["overlay"]) as o:
        session = model.session()
        session.run(HEIGHTS)
        assert session.run(WHO_TALLER).answer == "서우입니다."
        disabled = o.commit([ov.disable_rule("strict-height-transitivity")], **WHO)
        without = session.run(WHO_TALLER)
        assert without.answer != "서우입니다." and without.status is not mco.Status.ANSWERED
        o.undo(disabled["change_id"], **WHO)
        assert session.run(WHO_TALLER).answer == "서우입니다."


def test_a_candidate_applies_only_after_approval_and_a_rejected_one_never(setup):
    with mco.load(setup["model"], overlay=setup["overlay"]) as model, \
            mco.open_overlay(setup["model"], setup["overlay"]) as o:
        session = model.session()
        base_answer = session.run(LEAVES).answer
        pending = o.propose([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다")], actor="reviewer", reason="maybe")
        rejected = o.propose([ov.retract_edge(G, "손가락확인", "증명", "흙이말랐다")], actor="reviewer",
                             reason="maybe not")
        assert session.run(LEAVES).answer == base_answer
        assert session.run(FINGER).status is mco.Status.ANSWERED
        o.reject(rejected, rejected_by="owner", reason="the finger test is valid")
        approved = o.approve(pending, approved_by="owner")
        result, paths = say(session, LEAVES)
        assert result.status is mco.Status.ANSWERED
        origin = origin_of(paths, "잎시듦 -증명-> 흙이말랐다")
        assert origin["candidate_id"] == pending and origin["change_id"] == approved["change_id"]
        assert session.run(FINGER).status is mco.Status.ANSWERED           # the rejected retraction never applied
        with pytest.raises(mco.OverlayError):
            o.approve(rejected, approved_by="owner")


def test_base_only_overlay_only_both_and_a_withdrawn_conclusion_beside_a_kept_one(setup):
    with mco.load(setup["model"], overlay=setup["overlay"]) as model, \
            mco.open_overlay(setup["model"], setup["overlay"]) as o:
        session = model.session()
        # base only: both edges of the path are the base's, and carry no overlay origin
        result, paths = say(session, FINGER)
        assert result.status is mco.Status.ANSWERED and paths and all(origin is None for _, origin in paths)
        # overlay only: a new evidence node and concept, joined to the goal by overlay edges alone
        change = o.commit([ov.add_node(G, "뿌리참", examples=["뿌리가 화분에 꽉 찼다"]),
                           ov.add_node(G, "뿌리보임", examples=["화분 구멍 밖 뿌리"], layer="사례"),
                           ov.add_edge(G, "뿌리보임", "증명", "뿌리참"),
                           ov.add_edge(G, "뿌리참", "충족", "물을준다")], **WHO)
        result, paths = say(session, "화분 구멍 밖 뿌리")
        # the evidence is accepted (인정); the goal now has a second requirement (뿌리참), so the
        # dialogue still needs input for it
        assert result.raw_status == "인정" and result.answer == "뿌리보임 니까 뿌리참."
        assert [edge for edge, _ in paths] == ["뿌리보임 -증명-> 뿌리참", "뿌리참 -충족-> 물을준다"]
        assert all(origin["change_id"] == change["change_id"] for _, origin in paths)
        node = result.evidence.of_kind("graph_node")[0]
        assert node.text == "뿌리보임" and dict(node.detail)["origin"]["change_id"] == change["change_id"]
        o.undo(change["change_id"], **WHO)
        assert say(session, "화분 구멍 밖 뿌리")[1] == []
        # both: an overlay edge and a base edge on one path, each with its own origin
        both = o.commit([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다")], **WHO)
        result, paths = say(session, LEAVES)
        assert origin_of(paths, "잎시듦 -증명-> 흙이말랐다")["change_id"] == both["change_id"]
        assert origin_of(paths, "흙이말랐다 -충족-> 물을준다") is None
        # retracting the base edge withdraws the conclusion that used it; the one with its own proof stays
        o.commit([ov.retract_edge(G, "손가락확인", "증명", "흙이말랐다")], **WHO)
        withdrawn, paths = say(session, FINGER)
        assert withdrawn.status is not mco.Status.ANSWERED and paths == []
        kept, paths = say(session, LEAVES)
        assert kept.status is mco.Status.ANSWERED and origin_of(paths, "잎시듦 -증명-> 흙이말랐다")


SCRIPT = """
import json, sys, mco
model, overlay = sys.argv[1], sys.argv[2]
out = []
with mco.load(model, overlay=overlay) as m:
    s = m.session()
    for text in json.loads(sys.argv[3]):
        r = s.run(text)
        out.append([r.answer, r.status.value, [[e.kind, e.text, e.to_dict()["detail"].get("origin")] for e in r.evidence]])
print(json.dumps(out, ensure_ascii=False))
"""


def test_a_separate_process_on_the_same_base_and_overlay_answers_the_same(setup):
    with mco.open_overlay(setup["model"], setup["overlay"]) as o:
        o.commit([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다")], **WHO)
        o.commit([ov.retract_edge(G, "손가락확인", "증명", "흙이말랐다"),
                  ov.disable_rule("strict-height-transitivity")], **WHO)
    texts = [LEAVES, FINGER, HEIGHTS, WHO_TALLER]
    here = []
    with mco.load(setup["model"], overlay=setup["overlay"]) as model:
        session = model.session()
        for text in texts:
            r = session.run(text)
            here.append([r.answer, r.status.value, [[e.kind, e.text, e.to_dict()["detail"].get("origin")]
                                                    for e in r.evidence]])
    env = dict(os.environ, KG_ENCODER=os.environ.get("KG_ENCODER", "문자"), NAI_LANGUAGE="한국어")
    run = subprocess.run([sys.executable, "-c", SCRIPT, str(setup["model"]), str(setup["overlay"]),
                          json.dumps(texts, ensure_ascii=False)], cwd=ROOT, env=env, capture_output=True,
                         text=True, check=True)
    there = json.loads(run.stdout.strip().splitlines()[-1])
    assert there == json.loads(json.dumps(here, ensure_ascii=False))
    assert here[0][1] == "answered" and here[1][1] != "answered" and here[3][0] != "서우입니다."


def test_an_overlay_for_another_base_is_refused(setup):
    with pytest.raises(mco.OverlayBaseMismatchError):
        mco.load(setup["other"], overlay=setup["overlay"])
    with pytest.raises(mco.OverlayBaseMismatchError):
        mco.open_overlay(setup["other"], setup["overlay"])


def test_without_changes_the_answers_and_evidence_are_those_without_an_overlay(setup):
    texts = [FINGER, LEAVES, HEIGHTS, WHO_TALLER, "오늘 날씨 어때"]

    def run(**options):
        with mco.load(setup["model"], **options) as model:
            session = model.session()
            return [(r.answer, r.status, list(r.evidence), [(s.stage, s.summary) for s in r.trace])
                    for r in map(session.run, texts)]
    plain = run()
    assert run(overlay=setup["overlay"]) == plain
    with mco.open_overlay(setup["model"], setup["overlay"]) as o:
        change = o.commit([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다")], **WHO)
        o.undo(change["change_id"], **WHO)
    assert run(overlay=setup["overlay"]) == plain                  # changes that were all undone
    assert all("origin" not in dict(e.detail) for row in plain for e in row[2])


def test_a_conversation_snapshot_records_the_overlay_and_resumes_only_with_it(setup, tmp_path):
    with mco.open_overlay(setup["model"], setup["overlay"]) as o:
        o.commit([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다")], **WHO)
    snap = tmp_path / "talk.snapshot"
    with mco.load(setup["model"], overlay=setup["overlay"]) as model:
        session = model.session()
        session.run(HEIGHTS)
        answered = session.run(LEAVES)
        info = session.snapshot(snap)
    assert info.overlay["seq"] == 1
    with mco.load(setup["model"], overlay=setup["overlay"]) as model:
        resumed = model.resume(snap)
        assert resumed.run(LEAVES).answer == answered.answer
        assert resumed.run(WHO_TALLER).answer == "서우입니다."
    with mco.load(setup["model"]) as model:                 # the overlay is not attached: refused
        with pytest.raises(mco.SnapshotMismatchError):
            model.resume(snap)
    with mco.open_overlay(setup["model"], setup["overlay"]) as o:
        o.commit([ov.disable_rule("strict-height-transitivity")], **WHO)
    with mco.load(setup["model"], overlay=setup["overlay"]) as model:   # the overlay moved on: re-derived
        resumed = model.resume(snap)
        assert resumed.run(WHO_TALLER).answer != "서우입니다."
