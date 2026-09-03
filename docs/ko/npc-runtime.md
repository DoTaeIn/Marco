# NPC 런타임

`npc.py`는 대화창 하나를 NPC 하나로 오해하지 않기 위한 게임 계층이다. NPC는
자신의 그래프(`graph_path`), 장소, 목표, 에너지, 타 NPC에 대한 관계, 최근 기억을
갖고, `World`는 시간·공유 상태·사건 로그를 가진다. 그래프는 **무엇을 말할 수
있는가**를, 월드는 **그 말과 행동이 무엇을 바꾸는가**를 담당한다.

```python
from npc import NPC, World

world = World(state={"시장_개점": False})
world.add(NPC("mina", "미나", graph_path="graphs/graph_의료.kg",
              location="광장", goals=["약초 구하기"]))
world.add(NPC("jun", "준", location="광장"))

# 행동은 양쪽 기억과 관계에 남고, 게임의 공유 상태도 바꾼다.
event = world.interact("mina", "jun", "help", topic="약초 상자",
                       effects={"world": {"시장_개점": True}})
assert world.npcs["jun"].relation_to("mina").trust == 6

# 프레임/턴마다 한 번 호출한다. 같은 장소의 NPC들은 자율적으로 상호작용한다.
events = world.tick()

# NPC 그래프 대화도 사건으로 남는다. 실제 응답은 nai.Conversation이 만든다.
line = world.speak("mina", "약초가 필요합니다", target_id="jun")

# 세이브 파일에는 상태·관계·기억·사건이 모두 들어간다.
save_data = world.snapshot()
world = World.restore(save_data)
```

기본 상호작용은 `talk`, `help`, `trade`, `share`, `threaten`이다. 각각 관계에 주는
기본 변화가 있고, `effects`로 게임 고유 결과를 붙인다.

```python
world.interact("mina", "jun", "share", topic="도둑 소문",
               effects={
                   "relationship": {"trust": 10},
                   "world": {"경비_경계": True},
                   "quest": "도둑_추적_시작",
               })
```

`Event`는 렌더링과 게임 규칙이 읽는 계약이다. 퀘스트 시스템은 `event.kind`,
`event.topic`, `event.effects`를 보고 진행도를 바꾸고, UI는 `event.text`를 대사로
보여 주면 된다. NPC 런타임은 UI·저장소·전투 규칙을 호출하지 않으므로 Unity,
Unreal, 웹 서버 어느 쪽에도 동일하게 붙일 수 있다.

검증은 다음처럼 실행한다.

```bash
python npc.py --demo                         # 인코더 없이 한 턴 시뮬레이션
python -m unittest test_nai.py test_npc.py
```
