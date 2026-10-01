"""The merged base-plus-overlay view (marco/storage/graph_view.py).

A small pack is built in memory; the base is read through PackBase (and, once,
through mco's NativeModel, which satisfies the same reader protocol).
"""
from __future__ import annotations

import hashlib
import json

import pytest

from marco.storage import graph_text, ids
from marco.storage import overlay as ov
from marco.storage.graph_view import GraphView, PackBase, ViewError, apply_rule_changes

G = "graphs/g.kg"
H = "graphs/h.kg"
TEXT = """역할: 시험
목표: 결론
[개념]
결론: "결론이다"
중간: "중간이다"
[사례]
*증거: "증거가 있다" | "증거를 봤다"
[논증]
증거 -증명-> 중간
중간 -충족-> 결론
"""
OTHER = """역할: 다른 것
목표: 끝
[개념]
끝: "끝이다"
"""
RULES = {"schema": "nai-axioms-v1", "rules": [
    {"id": "r-a", "body": [["?x", "p", "?y"]], "head": ["?x", "q", "?y"]},
    {"id": "r-b", "body": [["?x", "q", "?y"]], "head": ["?x", "s", "?y"]}]}
MEMBERS = {G: TEXT.encode(), H: OTHER.encode(), "axioms/core.json": json.dumps(RULES).encode()}
MANIFEST = {"model": {"format": "nai-model", "version": 1, "language": None, "axioms": ["axioms/core.json"]}}
SHA = "ab" * 32
WHO = dict(actor="tester", source="test", reason="a test change", approved_by="owner")


@pytest.fixture
def base():
    return PackBase(MANIFEST, MEMBERS)


@pytest.fixture
def store(tmp_path):
    s = ov.OverlayStore.create(tmp_path / "o.overlay", base_sha256=SHA, base_build_id="b1", format_version="1.1")
    yield s
    s.close()


def _rev(store, kind, target):
    item = store.item(kind, target)
    return item["revision"] if item else 0


def add_edge(store, src, rel, dst, graph=G, **kw):
    eid = ids.edge_id(graph, src, rel, dst)
    return store.commit([ov.add_edge(graph, src, rel, dst, revision=_rev(store, "edge", eid), **kw)], **WHO)


def retract_edge(store, src, rel, dst, graph=G):
    eid = ids.edge_id(graph, src, rel, dst)
    return store.commit([ov.retract_edge(graph, src, rel, dst, revision=_rev(store, "edge", eid))], **WHO)


def add_node(store, name, examples, layer="개념", graph=G):
    nid = ids.node_id(graph, name)
    return store.commit([ov.add_node(graph, name, revision=_rev(store, "node", nid),
                                     data={"layer": layer, "examples": examples})], **WHO)


def test_base_only(base):
    view = GraphView(base, None, base_build_id="b1")
    assert view.seq == 0 and view.touched_graphs() == []
    assert view.graph(G) == graph_text.parse(TEXT)
    origins = view.origins(G)
    assert set(origins["nodes"]) == {"결론", "중간", "증거"}
    assert all(o == {"kind": "base", "build_id": "b1"} for o in origins["nodes"].values())
    assert len(origins["edges"]) == 2
    assert view.rules() == RULES["rules"]
    assert view.check() == []


def test_overlay_only_additions(base, store):
    add_node(store, "새것", ["새것이다"])
    seq, change = add_edge(store, "새것", "충족", "결론")
    view = GraphView(base, store, base_build_id="b1")
    g = view.graph(G)
    assert g["공통층"]["새것"] == ["새것이다"]
    assert ["새것", "충족", "결론"] in g["엣지"]
    origin = view.edge_origin(G, "새것", "충족", "결론")
    assert origin["kind"] == "overlay" and origin["change_id"] == change and origin["seq"] == seq
    assert origin["approved_by"] == "owner" and origin["actor"] == "tester"
    assert view.node_origin(G, "새것")["seq"] == 1
    assert view.node_origin(G, "결론")["kind"] == "base"
    assert view.touched_graphs() == [G] and view.check() == [G]
    # the merged graph is written as text that reads back equal
    assert graph_text.parse(view.text(G)) == g
    # the untouched graph is the base graph
    assert view.graph(H) == graph_text.parse(OTHER)


def test_base_and_overlay_make_one_path_with_two_origins(base, store):
    add_node(store, "끝점", ["끝점이다"])
    _seq, change = add_edge(store, "결론", "충족", "끝점")
    view = GraphView(base, store, base_build_id="b1")
    g = view.graph(G)
    adj = {}
    for a, r, b in g["엣지"]:
        adj.setdefault(a, []).append(b)
    # 중간 -> 결론 (base) -> 끝점 (overlay)
    assert "결론" in adj["중간"] and "끝점" in adj["결론"]
    first = view.edge_origin(G, "중간", "충족", "결론")
    second = view.edge_origin(G, "결론", "충족", "끝점")
    assert first == {"kind": "base", "build_id": "b1"}
    assert second["kind"] == "overlay" and second["change_id"] == change


def test_tombstoned_base_edge_is_gone_and_base_bytes_unchanged(base, store):
    before = hashlib.sha256(MEMBERS[G]).hexdigest()
    retract_edge(store, "중간", "충족", "결론")
    view = GraphView(base, store)
    assert ["중간", "충족", "결론"] not in view.graph(G)["엣지"]
    assert ids.edge_id(G, "중간", "충족", "결론") not in view.origins(G)["edges"]
    assert hashlib.sha256(MEMBERS[G]).hexdigest() == before
    assert base.graph(G)["엣지"] == [["증거", "증명", "중간"], ["중간", "충족", "결론"]]


def test_retract_then_add_again_gives_the_same_edge_id(base, store):
    eid = ids.edge_id(G, "중간", "충족", "결론")
    retract_edge(store, "중간", "충족", "결론")
    assert eid not in GraphView(base, store).origins(G)["edges"]
    _seq, change = add_edge(store, "중간", "충족", "결론")
    view = GraphView(base, store)
    assert view.graph(G)["엣지"].count(["중간", "충족", "결론"]) == 1
    assert view.origins(G)["edges"][eid]["change_id"] == change
    assert store.item("edge", eid)["id"] == eid


def test_retract_node_names_its_base_edges_from_node_edges(base, store):
    view = GraphView(base, store)
    request = view.retract_node(G, "중간", revision=0)
    assert sorted(map(tuple, request["payload"]["base_edges"])) == sorted(
        [("증거", "증명", "중간"), ("중간", "충족", "결론")])
    store.commit([request], **WHO)
    after = GraphView(base, store)
    g = after.graph(G)
    assert "중간" not in g["공통층"] and g["엣지"] == []
    assert store.counts()["edges_tombstoned"] == 2 and store.counts()["nodes_tombstoned"] == 1
    assert after.check() == [G]


def test_candidates_never_appear(base, store):
    pending = store.propose([ov.add_edge(G, "증거", "증명", "결론", revision=0)], actor="x", source="t", reason="r")
    rejected = store.propose([ov.retract_edge(G, "증거", "증명", "중간", revision=0)], actor="x", source="t",
                             reason="r")
    store.reject(rejected, rejected_by="owner", reason="no")
    view = GraphView(base, store)
    assert view.seq == 0 and view.touched_graphs() == []
    assert view.graph(G) == base.graph(G)
    store.approve(pending, approved_by="owner")
    view = GraphView(base, store)
    assert ["증거", "증명", "결론"] in view.graph(G)["엣지"]
    assert ["증거", "증명", "중간"] in view.graph(G)["엣지"]
    assert view.edge_origin(G, "증거", "증명", "결론")["candidate_id"] == pending


def test_a_pinned_view_does_not_move(base, store):
    add_edge(store, "증거", "증명", "결론")
    pinned = GraphView(base, store, at=1)
    before = pinned.graph(G)
    retract_edge(store, "증거", "증명", "결론")
    add_node(store, "늦은것", ["늦었다"])
    assert pinned.graph(G) == before
    assert GraphView(base, store, at=1).graph(G) == before
    assert ["증거", "증명", "결론"] not in GraphView(base, store).graph(G)["엣지"]
    assert GraphView(base, store, at=0).graph(G) == base.graph(G)


def test_a_delta_on_an_unknown_graph_is_refused(base, store):
    store.commit([ov.add_node("graphs/없음.kg", "x", revision=0, data={"examples": ["x"]})], **WHO)
    view = GraphView(base, store)
    assert view.unknown_graphs() == ["graphs/없음.kg"]
    with pytest.raises(ViewError, match="not in the base.*does not add whole graphs"):
        view.check()
    with pytest.raises(ViewError, match="not in the base"):
        view.graph("graphs/없음.kg")


def test_check_hook_refuses_and_writes_nothing(base, store):
    check = lambda s: GraphView(base, s).check()
    with pytest.raises(ViewError, match="not a node of the graph"):
        store.commit([ov.add_edge(G, "증거", "증명", "모르는것", revision=0)], check=check, **WHO)
    with pytest.raises(ViewError, match="no such edge"):
        store.commit([ov.retract_edge(G, "증거", "증명", "결론", revision=0)], check=check, **WHO)
    with pytest.raises(ViewError, match="example sentences"):
        store.commit([ov.add_node(G, "빈것", revision=0, data={"layer": "개념"})], check=check, **WHO)
    with pytest.raises(ViewError, match="no such rule"):
        store.commit([ov.disable_rule("r-없음", revision=0)], check=check, **WHO)
    with pytest.raises(ViewError, match="not in the base"):
        store.propose([ov.add_node("graphs/없음.kg", "x", revision=0, data={"examples": ["x"]})],
                      actor="x", source="t", reason="r", check=check)
    assert store.head() == (0, None) and store.candidates() == []
    seq, _ = store.commit([ov.add_edge(G, "증거", "증명", "결론", revision=0)], check=check, **WHO)
    assert seq == 1


def test_rules_view_disable_replace_add_with_origins(base, store):
    store.commit([ov.disable_rule("r-a", revision=0)], **WHO)
    new_b = {"id": "r-b", "body": [["?x", "p", "?y"]], "head": ["?x", "s", "?y"]}
    store.commit([ov.replace_rule("r-b", new_b, revision=0)], **WHO)
    added = {"id": "r-c", "body": [["?x", "s", "?y"]], "head": ["?x", "t", "?y"]}
    _seq, change = store.commit([ov.add_rule("r-c", added, revision=0)], **WHO)
    view = GraphView(base, store, base_build_id="b1")
    assert view.rules() == [new_b, added]
    origins = view.rule_origins()
    assert set(origins) == {"r-b", "r-c"} and origins["r-c"]["change_id"] == change
    assert view.check() == []
    # the same changes apply to any rule list (the runtime's own list has learned rules after the axioms)
    learned = {"id": "learned", "body": [], "head": ["a", "b", "c"]}
    assert apply_rule_changes(RULES["rules"] + [learned], view.rule_changes()) == [new_b, learned, added]
    # re-enabling a disabled base rule puts it back where it was
    store.commit([ov.add_rule("r-a", RULES["rules"][0], revision=1)], **WHO)
    assert GraphView(base, store).rules() == [RULES["rules"][0], new_b, added]


def test_native_model_is_a_base_reader(base, store, tmp_path):
    from mco.native.pack import canonical_json, write_model
    manager = {"format": "nai-kg-manager", "version": 1, "role": "r", "goal": "g",
               "nodes": [{"path": p, "role": "", "goal": "", "examples": []} for p in (G, H)], "edges": []}
    files = [{"path": p, "kind": "graph" if p.endswith(".kg") else "asset", "bytes": len(b),
              "sha256": hashlib.sha256(b).hexdigest(),
              "lf_normalized_sha256": hashlib.sha256(b).hexdigest(),
              "line_endings": {"crlf": 0, "lf": b.count(b"\n"), "cr": 0}} for p, b in sorted(MEMBERS.items())]
    pack = {"format": "nai-kgpack", "version": 3, "files": files, "manager": manager, "model": MANIFEST["model"]}
    path = tmp_path / "m.mco"
    data = canonical_json(pack)
    write_model(path, pack, MEMBERS, source_sha256=hashlib.sha256(data).hexdigest(), source_bytes=len(data))
    from mco.native import NativeModel
    add_node(store, "새것", ["새것이다"])
    add_edge(store, "새것", "충족", "결론")
    retract_edge(store, "증거", "증명", "중간")
    store.commit([ov.disable_rule("r-a", revision=0)], **WHO)
    with NativeModel.open(path) as native:
        a, b = GraphView(native, store), GraphView(base, store)
        assert a.graph(G) == b.graph(G) and a.rules() == b.rules() and a.text(G) == b.text(G)
        assert a.retract_node(G, "중간", revision=0) == b.retract_node(G, "중간", revision=0)
