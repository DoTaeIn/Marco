from bench.retrieval_diagnosis import classify


def test_argument_and_negative_edges_are_not_answer_equivalence():
    assert classify("a", "b", [("a", "부정", "b")]) == ("argument_neighbor", 1)
    assert classify("a", "b", [("a", "충족", "b")]) == ("argument_neighbor", 1)
    assert classify("a", "b", [("b", "설명함", "a")]) == ("explanation_neighbor", 1)


def test_distance_is_shortest_undirected_path_and_cycles_terminate():
    edges = [("a", "증명", "b"), ("b", "증명", "c"), ("c", "증명", "a"),
             ("c", "증명", "d")]
    assert classify("a", "d", edges) == ("connected_elsewhere", 2)
    assert classify("a", "outside", edges) == ("disconnected", None)
    assert classify("a", "a", edges) == ("exact", 0)
