"""The conversation identity graph (M1 step 1, docs/architecture/conversation-graph.md): nodes, aliases with their
turns, count edges with their origin, frames; carried in the snapshot (reasoning-context-v10)."""
import os

import pytest

os.environ.setdefault("KG_ENCODER", "문자")


def _context(language, turns):
    from pack_model import development_model
    from marco.reasoning.context import ReasoningContext
    context = ReasoningContext(model=development_model(language), effort=3)
    for turn in turns:
        context.turn(turn)
    return context


def _aliases(graph, form):
    return {(row["node"], row["text"]) for row in graph.aliases if row["form"] == form}


def test_one_node_per_holder_thing_and_place_with_their_aliases_and_counts():
    context = _context("english", ["My cousin Wren has 5 figs.", "Dr. Tobin has 3 cups.",
                                   "There are 4 figs in the red shed.", "Wren gave Tobin 2 figs."])
    graph = context.conversation_graph()
    wren, tobin = graph.id_of("holder", "Wren"), graph.id_of("holder", "Tobin")
    shed, figs, cups = graph.id_of("place", "red shed"), graph.id_of("thing", "figs"), graph.id_of("thing", "cups")
    assert None not in (wren, tobin, shed, figs, cups)
    assert len(graph.of_kind("holder")) == 2 and len(graph.of_kind("place")) == 1 and len(graph.of_kind("thing")) == 2
    assert (wren, "cousin") in _aliases(graph, "relation") and (tobin, "Dr. Tobin") in _aliases(graph, "title")
    assert (figs, "fig") in _aliases(graph, "number")
    # a count said by a statement, and one replay computed from a transfer
    assert graph.counts[(tobin, cups)] == {"holder": tobin, "thing": cups, "value": 3, "origin": "said", "turns": [1]}
    assert graph.counts[(wren, figs)]["value"] == 3 and graph.counts[(wren, figs)]["origin"] == "computed"
    assert graph.counts[(wren, figs)]["turns"] == [0, 3]
    assert graph.counts[(tobin, figs)]["value"] is None          # a receiver whose count was never said
    assert graph.holders_of(figs) and sorted(graph.things_of(tobin)) == sorted([cups, figs])
    assert graph.of_key("Wren figs") == (wren, figs) and graph.key(wren, figs) == "Wren figs"


def test_korean_titles_after_a_name_and_a_possessive_relation_before_it_are_aliases():
    context = _context("한국어", ["제 친구 미경은 공책이 3권 있어.", "김 과장님은 상자가 4개 있어.", "미경이 김 과장님에게 공책을 1권 줬어."])
    graph = context.conversation_graph()
    mi, kim = graph.id_of("holder", "미경"), graph.id_of("holder", "김 과장")
    assert (mi, "친구") in _aliases(graph, "relation") and (kim, "김 과장님") in _aliases(graph, "title")
    assert graph.find("김 과장님", kinds=("holder",)) == [kim]
    notebook = graph.id_of("thing", "공책")
    assert graph.counts[(mi, notebook)]["value"] == 2 and graph.counts[(mi, notebook)]["origin"] == "computed"


def test_the_snapshot_carries_the_graph_and_node_ids_are_stable_and_never_reused():
    from pack_model import development_model
    from marco.reasoning.context import ReasoningContext
    context = _context("english", ["Wren has 5 figs.", "Tobin has 3 figs.", "How many figs does Wren have?"])
    before = context.conversation_graph().to_dict()
    snapshot = context.snapshot()
    assert snapshot["schema"] == "reasoning-context-v10" and snapshot["graph"]["ids"] == before["ids"]
    restored = ReasoningContext(model=development_model("english"), effort=3)
    restored.restore(snapshot)
    assert restored.conversation_graph().to_dict()["ids"] == before["ids"]
    assert restored.conversation_graph().frames == before["frames"]
    restored.turn("Ula has 2 figs.")
    after = restored.conversation_graph()
    assert after.id_of("holder", "Ula") not in {node_id for _k, _n, node_id in before["ids"]}
    assert after.id_of("holder", "Wren") == context.conversation_graph().id_of("holder", "Wren")


def test_a_v9_snapshot_restores_with_its_graph_rebuilt():
    from pack_model import development_model
    from marco.reasoning.context import ReasoningContext
    context = _context("english", ["Wren has 5 figs.", "Tobin has 3 figs."])
    snapshot = dict(context.snapshot(), schema="reasoning-context-v9")
    snapshot.pop("graph")
    restored = ReasoningContext(model=development_model("english"), effort=3)
    restored.restore(snapshot)
    graph = restored.conversation_graph()
    assert graph.value(graph.id_of("holder", "Wren"), graph.id_of("thing", "figs")) == 5


def test_a_pointer_resolved_and_a_which_person_reply_are_alias_edges_with_their_turn():
    context = _context("english", ["My cousin Wren has 5 figs.", "My cousin Tobin has 3 figs.",
                                   "How many figs does my cousin have?", "Wren.", "How many does she have now?"])
    graph = context.conversation_graph()
    wren = graph.id_of("holder", "Wren")
    assert (wren, "my cousin") in _aliases(graph, "reply")
    assert (wren, "she") in _aliases(graph, "pointer")
    assert all(isinstance(row["turn"], int) for row in graph.aliases if row["form"] in ("reply", "pointer"))


def test_the_trace_lists_the_nodes_a_turn_read():
    context = _context("english", ["Wren has 5 figs.", "Tobin has 3 figs."])
    graph = context.conversation_graph()
    result = context.turn("How many figs do Wren and Tobin have in total?")
    assert set(context._nodes_read(result)) == {graph.id_of("holder", "Wren"), graph.id_of("holder", "Tobin"),
                                                graph.id_of("thing", "figs")}


@pytest.mark.xfail(reason="step 3 moves the holder/thing split to the reader; today the key of '… 세 개, 컵 두 개를 …' "
                          "makes 컵 a holder", strict=True)
def test_a_list_of_two_things_of_one_holder_is_one_holder_node():
    context = _context("한국어", ["보늬는 연필 세 개, 컵 두 개를 가지고 있어."])
    assert [node["name"] for node in context.conversation_graph().of_kind("holder")] == ["보늬"]
