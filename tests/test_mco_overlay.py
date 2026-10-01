"""The mco surface of the Persistent Overlay Infrastructure (mco/overlay.py, the CLI, inspect).

Additions only: mco API version 1 is unchanged. Every change is an explicit call
that names its approver; the store is MARCO's, reached through the MARCO backend.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import mco
from mco import overlay as ov
from mco.cli import main
from tests.test_overlay_runtime import G, LANGUAGE, build_source

pytestmark = pytest.mark.language("한국어")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mco-overlay")
    root = build_source(tmp / "src")
    out = {}
    for fmt in ("native", "compat"):
        out[fmt] = tmp / f"model-{fmt}.mco"
        mco.compile(root, out[fmt], name="small", language=LANGUAGE, format=fmt)
    other = build_source(tmp / "src2")
    (other / G).write_text((other / G).read_text(encoding="utf-8") + "\n# another build\n", encoding="utf-8")
    out["other"] = tmp / "other.mco"
    mco.compile(other, out["other"], name="other", language=LANGUAGE, format="native")
    return out


def _cli(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    return main(list(argv), stdout=out), out.getvalue()


def test_builders_are_plain_dictionaries():
    assert ov.add_edge(G, "a", "증명", "b") == {"op": "ADD_EDGE", "graph": G, "src": "a", "rel": "증명", "dst": "b"}
    assert ov.add_node(G, "n", examples=["x"], layer="사례")["layer"] == "사례"
    assert ov.retract_node(G, "n", revision=2) == {"op": "RETRACT_NODE", "graph": G, "name": "n", "revision": 2}
    assert ov.disable_rule("r") == {"op": "DISABLE_RULE", "rule_id": "r"}
    assert ov.edge_id(G, "a", "증명", "b").startswith("e:")


@pytest.mark.parametrize("fmt", ["native", "compat"])
def test_create_binds_to_the_model_and_another_model_is_refused(models, tmp_path, fmt):
    path = tmp_path / "o.overlay"
    status = mco.create_overlay(models[fmt], path)
    info = mco.inspect(models[fmt])
    assert status["base"]["build_id"] == info.build_id and status["head"] == {"seq": 0, "change_id": None}
    if fmt == "native":
        assert status["base"]["content_sha256"] == info.manifest["mco"]["content_sha256"]
    with pytest.raises(mco.OverlayError, match="exists already"):
        mco.create_overlay(models[fmt], path)
    with pytest.raises(mco.OverlayBaseMismatchError):
        mco.open_overlay(models["other"], path)
    with pytest.raises(mco.OverlayBaseMismatchError):
        mco.load(models["other"], overlay=path)
    with pytest.raises(mco.OverlayError, match="no overlay at"):
        mco.load(models[fmt], overlay=tmp_path / "missing.overlay")


def test_the_native_and_compat_files_of_one_pack_share_the_content_identity(models, tmp_path):
    a = mco.create_overlay(models["native"], tmp_path / "a")
    b = mco.create_overlay(models["compat"], tmp_path / "b")
    assert a["base"]["content_sha256"] == b["base"]["content_sha256"]
    assert a["base"]["build_id"] == b["base"]["build_id"]


def test_commit_propose_approve_reject_undo_and_history(models, tmp_path):
    path = tmp_path / "o.overlay"
    mco.create_overlay(models["native"], path)
    with mco.open_overlay(models["native"], path) as o:
        first = o.commit([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다")], approved_by="owner", reason="seen")
        assert first["seq"] == 1 and o.head() == first and o.counts()["edges_added"] == 1
        candidate = o.propose([ov.disable_rule("strict-height-transitivity")], actor="reviewer", reason="test")
        assert o.counts()["rules_disabled"] == 0 and o.status()["pending"] == 1
        approved = o.approve(candidate, approved_by="owner")
        assert approved["seq"] == 2 and o.counts()["rules_disabled"] == 1
        rejected = o.propose([ov.retract_edge(G, "손가락확인", "증명", "흙이말랐다")], actor="reviewer", reason="t")
        o.reject(rejected, rejected_by="owner", reason="not observed")
        assert o.counts()["edges_tombstoned"] == 0
        assert [c["status"] for c in o.candidates()] == ["approved", "rejected"]
        undone = o.undo(first["change_id"], approved_by="owner", reason="mistake")
        assert undone["seq"] == 3 and o.counts()["edges_added"] == 0
        history = o.history(ov.edge_id(G, "잎시듦", "증명", "흙이말랐다"))
        assert [h["op"] for h in history] == ["ADD_EDGE", "RESTORE"]
        assert history[0]["approval"]["by"] == "owner" and history[0]["reason"] == "seen"
        # revisions are filled from the store; a stale explicit one is refused
        o.commit([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다")], approved_by="owner", reason="again")
        with pytest.raises(mco.OverlayError, match="revision"):
            o.commit([ov.retract_edge(G, "잎시듦", "증명", "흙이말랐다", revision=0)], approved_by="owner",
                     reason="stale")
        # RETRACT NODE names the node's base edges itself
        o.commit([ov.retract_node(G, "손가락확인")], approved_by="owner", reason="gone")
        assert o.counts()["nodes_tombstoned"] == 1 and o.counts()["edges_tombstoned"] == 1


def test_a_change_the_model_cannot_take_is_refused_and_nothing_is_written(models, tmp_path):
    path = tmp_path / "o.overlay"
    mco.create_overlay(models["native"], path)
    with mco.open_overlay(models["native"], path) as o:
        for bad, why in [(ov.add_node("graphs/없는.kg", "x", examples=["x"]), "does not add whole graphs"),
                         (ov.add_edge(G, "잎시듦", "증명", "없는노드"), "not a node of the graph"),
                         (ov.retract_edge(G, "잎시듦", "증명", "흙이말랐다"), "no such edge"),
                         (ov.disable_rule("없는-규칙"), "no such rule"),
                         (ov.add_rule({"id": "r", "body": []}), "head")]:
            with pytest.raises(mco.OverlayError, match=why):
                o.commit([bad], approved_by="owner", reason="bad")
            with pytest.raises(mco.OverlayError, match=why):
                o.propose([bad], actor="someone", reason="bad")
        assert o.head() == {"seq": 0, "change_id": None} and o.candidates() == []
        with pytest.raises(mco.InvalidInputError):
            o.commit([{"op": "LEARN"}], approved_by="owner", reason="x")
    with pytest.raises(mco.OverlayError, match="one writer"):
        with mco.open_overlay(models["native"], path), mco.open_overlay(models["native"], path):
            pass


def test_inspect_shows_the_overlay_without_running_anything(models, tmp_path):
    path = tmp_path / "o.overlay"
    mco.create_overlay(models["native"], path)
    with mco.open_overlay(models["native"], path) as o:
        o.commit([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다"), ov.disable_rule("strict-height-transitivity")],
                 approved_by="owner", reason="r")
    info = mco.inspect(models["native"], overlay=path)
    note = next(n for n in info.notes if n.startswith("overlay " + str(path)))
    assert "head seq 1" in note and "edges +1 -0" in note and "rules +0 ~0 -1" in note
    assert info.manifest["overlay"]["counts"]["edges_added"] == 1
    assert info.manifest["mco"]["supports"] == {"overlay": False, "snapshot": False}   # the file holds none
    code, text = _cli("inspect", str(models["native"]), "--overlay", str(path))
    assert code == 0 and "head seq 1" in text and "bound to content" in text
    code = ("import sys, mco; mco.inspect(sys.argv[1], overlay=sys.argv[2]); "
            "print([m for m in ('engine', 'pack_model', 'views.kgpack_ui') if m in sys.modules])")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    out = subprocess.run([sys.executable, "-c", code, str(models["native"]), str(path)], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"


def test_cli_overlay_commands(models, tmp_path):
    model, path = str(models["compat"]), str(tmp_path / "o.overlay")
    code, text = _cli("overlay", "create", model, path)
    assert code == 0 and json.loads(text)["head"]["seq"] == 0
    delta = json.dumps(ov.add_edge(G, "잎시듦", "증명", "흙이말랐다"), ensure_ascii=False)
    code, text = _cli("overlay", "commit", model, path, "--delta", delta, "--approved-by", "owner", "--reason", "r")
    assert code == 0 and json.loads(text)["seq"] == 1
    code, text = _cli("overlay", "propose", model, path, "--delta",
                      json.dumps(ov.disable_rule("strict-height-transitivity")), "--actor", "a", "--reason", "r")
    candidate = json.loads(text)["candidate_id"]
    code, text = _cli("overlay", "candidates", model, path, "--status", "pending")
    assert [c["candidate_id"] for c in json.loads(text)] == [candidate]
    code, text = _cli("overlay", "approve", model, path, candidate, "--approved-by", "owner")
    assert code == 0 and json.loads(text)["seq"] == 2
    code, text = _cli("overlay", "undo", model, path, "2", "--approved-by", "owner", "--reason", "back")
    assert code == 0 and json.loads(text)["seq"] == 3
    code, text = _cli("overlay", "history", model, path, ov.edge_id(G, "잎시듦", "증명", "흙이말랐다"))
    assert [h["op"] for h in json.loads(text)] == ["ADD_EDGE"]
    code, text = _cli("overlay", "status", model, path)
    status = json.loads(text)
    assert status["head"]["seq"] == 3 and status["counts"]["edges_added"] == 1 and status["counts"]["rules_disabled"] == 0
    # a refused change is an mco error: exit status 1, nothing written
    code, _ = _cli("overlay", "commit", model, path, "--delta", json.dumps(ov.add_node("graphs/x.kg", "n", examples=["e"])),
                   "--approved-by", "owner", "--reason", "r")
    assert code == 1 and json.loads(_cli("overlay", "status", model, path)[1])["head"]["seq"] == 3
    # approver is required
    with pytest.raises(SystemExit):
        _cli("overlay", "commit", model, path, "--delta", delta, "--reason", "r")


def test_without_a_marco_runtime_the_overlay_is_not_available(models, tmp_path):
    code = ("import sys, mco\n"
            "try:\n    mco.create_overlay(sys.argv[1], sys.argv[2])\n"
            "except mco.BackendUnavailableError as e:\n    print('unavailable')\n")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["MCO_MARCO_ROOT"] = str(tmp_path)          # not a MARCO checkout
    out = subprocess.run([sys.executable, "-c", code, str(models["native"]), str(tmp_path / "o")], cwd=ROOT,
                         env=env, capture_output=True, text=True, check=True).stdout.strip()
    assert out == "unavailable" and not (tmp_path / "o").exists()
