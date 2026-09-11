"""대화예절 그래프가 업무 질문을 가로채지 않는 최소 회귀 검사."""
import engine


def _selfcheck():
    index = engine.graph_index()
    assert engine.pick_graph("고마워", index)[0] == "graphs/graph_대화예절.kg"
    assert engine.pick_graph("안녕하세요", index)[0] == "graphs/graph_대화예절.kg"
    assert engine.pick_graph("12만원 나왔어", index)[0] != "graphs/graph_대화예절.kg"
    assert engine.pick_graph("2등을 제쳤다", index)[0] != "graphs/graph_대화예절.kg"


if __name__ == "__main__":
    _selfcheck()
    print("대화예절 라우팅: ok")
