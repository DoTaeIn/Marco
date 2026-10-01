"""Graph text writer (marco/storage/graph_text.py): the merged view goes back to .kg text.

The engine reads .kg files, so a graph the overlay touches is written as text. The
writer is proved on every graph under graphs/: read_kg(write(read_kg(file))) equals
read_kg(file). A graph or a change that has no exact text is refused, not hidden.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from marco.storage import graph_text
from marco.storage import overlay as ov
from marco.storage.graph_view import GraphView, ViewError

ROOT = Path(__file__).resolve().parents[1]
ALL_GRAPHS = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "graphs").glob("*.kg"))


def _ordered_equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(_ordered_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_ordered_equal(x, y) for x, y in zip(a, b))
    return a == b


def test_every_graph_round_trips_through_the_writer(tmp_path):
    import engine
    assert len(ALL_GRAPHS) > 800
    classes: Counter = Counter()
    failed = {}
    reordered = []
    for rel in ALL_GRAPHS:
        g = engine.read_kg(str(ROOT / rel))
        try:
            text = graph_text.write(g, rel)
        except graph_text.GraphTextError as exc:
            classes["no exact text"] += 1
            failed[rel] = str(exc)
            continue
        out = tmp_path / Path(rel).name
        out.write_text(text, encoding="utf-8")
        again = engine.read_kg(str(out))
        if again != g:
            classes["read_kg differs"] += 1
            failed[rel] = sorted(k for k in set(g) | set(again) if g.get(k) != again.get(k))
        elif not _ordered_equal(again, g):
            reordered.append(rel)
    print("\ngraphs checked %d, mismatches by class %s, equal but with another dict key order %d"
          % (len(ALL_GRAPHS), dict(classes), len(reordered)))
    assert not failed, failed


def test_parse_agrees_with_the_mco_reader_for_every_graph():
    from mco.native.kgtext import parse_kg
    for rel in ALL_GRAPHS:
        data = (ROOT / rel).read_bytes()
        assert _ordered_equal(graph_text.parse(data, rel), parse_kg(data, rel)), rel


def test_parse_plus_engine_merge_is_read_kg():
    import engine
    for rel in ALL_GRAPHS[:40]:
        g = graph_text.parse((ROOT / rel).read_bytes(), rel)
        engine._merge_shared_net(g)
        assert g == engine.read_kg(str(ROOT / rel)), rel


SMALL = """역할: 시험
목표: 결론
임계값: 0.4 / 0.7
전진관계: 확인함, 이어짐
[개념]
결론 {원 = 총액 / 인원}: "결론이다"
총액 {원}: "총액이다"
[공리]
법칙: "법칙이다"
[개념]
뒤의개념 {점 >= 3.5}: "뒤에 있다"
[사례]
*증거@문서: "증거가 있다" | ""
옮김 {등 <- 순위}: "옮긴다"
[무관]
_잡담: "잡담"
[논증]
증거 -확인함-> 결론
[개념망]
작은것 -상위-> 큰것
[물음]
총액: 얼마예요?
[대사]
A: 혹시 {claim} 말씀인가요?
"""


def test_every_construct_of_the_format_is_written():
    g = graph_text.parse(SMALL)
    text = graph_text.write(g)
    assert _ordered_equal(graph_text.parse(text), g)
    assert list(g["공통층"]) == ["결론", "총액", "법칙", "뒤의개념"] and g["공리"] == ["법칙"]


@pytest.mark.parametrize("change, why", [
    (lambda g: g["공통층"].__setitem__("이름:콜론", ["x"]), "does not read back equal"),
    (lambda g: g["사례층"].__setitem__("예시", ["a | b"]), "does not read back equal"),
    (lambda g: g["사례층"].__setitem__("주석", ["값 # 메모"]), "does not read back equal"),
    (lambda g: g["엣지"].append(["a", "r", "b, c"]), "does not read back equal"),
    (lambda g: g["사례층"].__setitem__("빈", []), "does not parse"),
])
def test_a_graph_without_exact_text_is_refused(change, why):
    g = graph_text.parse(SMALL)
    change(g)
    with pytest.raises(graph_text.GraphTextError, match=why):
        graph_text.write(g)
    assert graph_text.unwritable(g)


class _Base:
    """A base reader whose one graph has a node name that no .kg text can hold."""

    def __init__(self):
        self.g = graph_text.parse(SMALL)
        self.g["공통층"]["이름:콜론"] = ["x"]

    def graph_ids(self):
        return ["graphs/s.kg"]

    def graph(self, graph):
        return deepcopy(self.g)

    def node_edges(self, graph, name):
        return []

    def rules(self):
        return []


def test_overlay_changes_on_a_graph_without_exact_text_are_refused(tmp_path):
    base = _Base()
    with ov.OverlayStore.create(tmp_path / "o", base_sha256="cd" * 32, base_build_id="b",
                                format_version="1.1") as store:
        view = GraphView(base, store)
        assert view.writable("graphs/s.kg")
        assert view.graph("graphs/s.kg") == base.g          # untouched: the base graph, as it is
        check = lambda s: GraphView(base, s).check()
        with pytest.raises(ViewError, match="cannot be written back as .kg text exactly"):
            store.commit([ov.add_edge("graphs/s.kg", "결론", "확인함", "총액", revision=0)], check=check,
                         actor="t", source="t", reason="r", approved_by="owner")
        assert store.head() == (0, None)


def test_an_added_node_without_exact_text_is_refused(tmp_path):
    from marco.storage.graph_view import PackBase
    base = PackBase({}, {"graphs/s.kg": SMALL.encode()})
    with ov.OverlayStore.create(tmp_path / "o", base_sha256="cd" * 32, base_build_id="b",
                                format_version="1.1") as store:
        check = lambda s: GraphView(base, s).check()
        with pytest.raises(ViewError, match="cannot be written back"):
            store.commit([ov.add_node("graphs/s.kg", "새것", revision=0, data={"examples": ["a | b"]})],
                         check=check, actor="t", source="t", reason="r", approved_by="owner")
        assert store.head() == (0, None)
