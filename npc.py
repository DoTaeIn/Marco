# -*- coding: utf-8 -*-
"""게임 안에서 NPC가 서로 관계를 만들고 세계 상태를 바꾸는 작은 런타임.

이 모듈은 렌더러나 특정 게임 엔진에 묶이지 않는다. 게임은 ``World.tick()``을
호출하고 반환된 사건을 퀘스트·애니메이션·저장 시스템에 연결하면 된다. 대화의
내용 판정은 기존 :class:`nai.Conversation`에 맡기므로, NPC 런타임이 근거 없는
대사를 별도로 만들어 내지 않는다.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional


def _bounded(value: int, low: int = -100, high: int = 100) -> int:
    return max(low, min(high, value))


@dataclass
class Relationship:
    """한 NPC가 다른 NPC를 어떻게 보는지 나타내는 저장 가능한 상태."""

    affinity: int = 0
    trust: int = 0
    fear: int = 0

    def change(self, *, affinity: int = 0, trust: int = 0, fear: int = 0) -> None:
        self.affinity = _bounded(self.affinity + affinity)
        self.trust = _bounded(self.trust + trust)
        self.fear = _bounded(self.fear + fear)


@dataclass
class Event:
    """세계에서 일어난 한 가지 관찰 가능한 변화."""

    tick: int
    actor: str
    kind: str
    target: Optional[str] = None
    topic: Optional[str] = None
    text: Optional[str] = None
    effects: dict[str, Any] = field(default_factory=dict)


@dataclass
class NPC:
    """NPC의 정체성과 변하는 상태.

    ``graph_path``는 선택 사항이다. 있으면 ``speak``가 해당 .kg를 통해 말하고,
    없으면 게임이 전달한 말만 사건으로 기록한다. 따라서 관계/생활 시뮬레이션은
    모델이나 인코더가 없는 서버에서도 테스트할 수 있다.
    """

    id: str
    name: str
    graph_path: Optional[str] = None
    location: str = ""
    goals: list[str] = field(default_factory=list)
    energy: int = 100
    facts: dict[str, Any] = field(default_factory=dict)
    relationships: dict[str, Relationship] = field(default_factory=dict)
    memories: list[Event] = field(default_factory=list)
    _conversation: Any = field(default=None, init=False, repr=False, compare=False)

    def relation_to(self, other_id: str) -> Relationship:
        if other_id == self.id:
            raise ValueError("NPC는 자기 자신과 관계를 만들 수 없습니다")
        return self.relationships.setdefault(other_id, Relationship())

    def remember(self, event: Event, *, limit: int = 100) -> None:
        self.memories.append(event)
        del self.memories[:-limit]


# 숫자는 의도가 아니라 기본적인 사회적 결과다. 게임은 interact(..., effects=...)
# 로 퀘스트/성격/아이템에 맞는 결과를 덧씌울 수 있다.
SOCIAL_EFFECTS: dict[str, dict[str, int]] = {
    "talk": {"affinity": 1},
    "help": {"affinity": 8, "trust": 6},
    "trade": {"trust": 2},
    "share": {"affinity": 3, "trust": 4},
    "threaten": {"affinity": -8, "fear": 10, "trust": -4},
}


class World:
    """NPC 집단의 시간, 공유 상태, 사건 기록을 소유한다."""

    def __init__(self, *, state: Optional[dict[str, Any]] = None,
                 conversation_factory: Optional[Callable[[str], Any]] = None):
        self.tick_count = 0
        self.npcs: dict[str, NPC] = {}
        self.state: dict[str, Any] = dict(state or {})
        self.events: list[Event] = []
        self._conversation_factory = conversation_factory

    def add(self, npc: NPC) -> NPC:
        if not npc.id:
            raise ValueError("NPC id가 비어 있습니다")
        if npc.id in self.npcs:
            raise ValueError("이미 등록된 NPC id입니다: %s" % npc.id)
        self.npcs[npc.id] = npc
        return npc

    def _npc(self, npc_id: str) -> NPC:
        try:
            return self.npcs[npc_id]
        except KeyError as error:
            raise ValueError("등록되지 않은 NPC입니다: %s" % npc_id) from error

    def _record(self, event: Event, *witnesses: NPC) -> Event:
        self.events.append(event)
        for npc in witnesses:
            npc.remember(event)
        return event

    def interact(self, actor_id: str, target_id: str, kind: str, *,
                 topic: Optional[str] = None, text: Optional[str] = None,
                 effects: Optional[dict[str, Any]] = None) -> Event:
        """두 NPC의 상호작용을 실행하고 양쪽 관계와 공유 상태를 갱신한다."""
        actor, target = self._npc(actor_id), self._npc(target_id)
        if actor is target:
            raise ValueError("상호작용 대상은 다른 NPC여야 합니다")
        if kind not in SOCIAL_EFFECTS:
            raise ValueError("알 수 없는 상호작용입니다: %s" % kind)

        change = dict(SOCIAL_EFFECTS[kind])
        supplied = dict(effects or {})
        relation_change = supplied.pop("relationship", {})
        change.update({key: int(value) for key, value in relation_change.items()
                       if key in ("affinity", "trust", "fear")})
        actor.relation_to(target.id).change(**change)
        # 상대는 같은 사건을 완전히 똑같이 느끼지 않는다. 도움은 신뢰를 만들지만
        # 위협은 공포와 반감을 남긴다.
        target.relation_to(actor.id).change(**change)
        for key, value in supplied.pop("world", {}).items():
            self.state[key] = value
        actor.energy = _bounded(actor.energy - int(supplied.pop("actor_energy", 2)), 0, 100)
        event = Event(self.tick_count, actor.id, kind, target.id, topic, text,
                      {"relationship": change, **supplied})
        return self._record(event, actor, target)

    def speak(self, actor_id: str, text: str, *, target_id: Optional[str] = None) -> Event:
        """그래프 대화를 한 턴 진행하고, 그 결과를 세계 사건으로 남긴다."""
        actor = self._npc(actor_id)
        if not text.strip():
            raise ValueError("말할 내용이 비어 있습니다")
        reply = None
        if actor.graph_path:
            if actor._conversation is None:
                factory = self._conversation_factory
                if factory is None:
                    from nai import Conversation
                    factory = Conversation
                actor._conversation = factory(actor.graph_path)
            reply = actor._conversation.reply(text)
        answer = getattr(reply, "text", text)
        topic = getattr(reply, "topic", None)
        event = Event(self.tick_count, actor.id, "speak", target_id, topic, answer,
                      {"intent": getattr(reply, "intent", None),
                       "path": getattr(reply, "path", [])})
        witnesses = [actor] + ([self._npc(target_id)] if target_id else [])
        return self._record(event, *witnesses)

    def tick(self) -> list[Event]:
        """시간을 한 칸 진행해, 같은 장소의 NPC가 최소한의 자율 행동을 하게 한다.

        에너지가 낮으면 휴식하고, 그렇지 않으면 같은 장소에서 가장 친한 상대에게
        말을 건다. 게임 AI는 반환 사건을 보고 더 높은 수준의 행동을 추가할 수 있다.
        """
        self.tick_count += 1
        made: list[Event] = []
        for npc in self.npcs.values():
            if npc.energy < 20:
                npc.energy = min(100, npc.energy + 15)
                made.append(self._record(Event(self.tick_count, npc.id, "rest",
                                               effects={"energy": npc.energy}), npc))
                continue
            candidates = [other for other in self.npcs.values()
                          if other is not npc and other.location == npc.location]
            if candidates:
                target = max(candidates, key=lambda other: npc.relation_to(other.id).affinity)
                made.append(self.interact(npc.id, target.id, "talk", topic=npc.goals[0] if npc.goals else None))
        return made

    def snapshot(self) -> dict[str, Any]:
        """JSON으로 바로 저장할 수 있는 월드 상태. 그래프 대화 캐시는 저장하지 않는다."""
        def npc_data(npc: NPC) -> dict[str, Any]:
            return {"id": npc.id, "name": npc.name, "graph_path": npc.graph_path,
                    "location": npc.location, "goals": npc.goals, "energy": npc.energy,
                    "facts": npc.facts,
                    "relationships": {key: asdict(value) for key, value in npc.relationships.items()},
                    "memories": [asdict(event) for event in npc.memories]}
        return {"tick": self.tick_count, "state": self.state,
                "npcs": [npc_data(npc) for npc in self.npcs.values()],
                "events": [asdict(event) for event in self.events]}

    @classmethod
    def restore(cls, data: dict[str, Any], **kwargs: Any) -> "World":
        world = cls(state=data.get("state"), **kwargs)
        world.tick_count = int(data.get("tick", 0))
        for raw in data.get("npcs", []):
            npc = NPC(id=raw["id"], name=raw["name"], graph_path=raw.get("graph_path"),
                      location=raw.get("location", ""), goals=list(raw.get("goals", [])),
                      energy=int(raw.get("energy", 100)), facts=dict(raw.get("facts", {})))
            npc.relationships = {key: Relationship(**value)
                                 for key, value in raw.get("relationships", {}).items()}
            npc.memories = [Event(**event) for event in raw.get("memories", [])]
            world.add(npc)
        world.events = [Event(**event) for event in data.get("events", [])]
        return world


def _demo() -> World:
    """문서와 CI에서 쓸, 인코더 없는 작은 마을 한 턴."""
    world = World(state={"market_open": False})
    world.add(NPC("mina", "미나", location="광장", goals=["빵 판매"]))
    world.add(NPC("jun", "준", location="광장", goals=["소문 듣기"]))
    world.interact("mina", "jun", "help", topic="가판대 설치",
                   effects={"world": {"market_open": True}})
    world.tick()
    return world


def _main() -> int:
    parser = argparse.ArgumentParser(description="NPC 관계·상태 런타임")
    parser.add_argument("--demo", action="store_true", help="인코더 없이 마을 한 턴을 JSON으로 출력")
    args = parser.parse_args()
    if not args.demo:
        parser.error("--demo를 사용하거나 게임 코드에서 World를 import하십시오")
    print(json.dumps(_demo().snapshot(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
