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
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional


def _bounded(value: int, low: int = -100, high: int = 100) -> int:
    return max(low, min(high, value))


@dataclass
class Relationship:
    """한 NPC가 다른 NPC를 어떻게 보는지 나타내는 저장 가능한 상태."""

    kind: str = "stranger"
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
    # 그래프는 무엇을 아는가, 목소리는 어떻게 말하는가. 같은 그래프에 목소리만
    # 달리 붙이면 마을 사람 스무 명이 같은 지식을 공유하며 각자 다르게 말한다.
    목소리: Optional[str] = None
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


_조사쌍 = {"은": "는", "는": "은", "이": "가", "가": "이", "을": "를", "를": "을",
           "과": "와", "와": "과"}


def 조사맞추기(글: str, 이름들) -> str:
    """이름 뒤 조사를 받침에 맞게 고친다. '톰가' -> '톰이'.

    engine 의 조사고치기() 와 같은 일을 하지만 여기 따로 둔다. npc 런타임은
    인코더 없는 서버에서도 돌아야 해서 engine 을 import 하지 않는다."""
    for 이름 in sorted({x for x in 이름들 if x}, key=len, reverse=True):
        끝 = ord(이름[-1])
        if not (0xAC00 <= 끝 <= 0xD7A3):
            continue
        받침 = (끝 - 0xAC00) % 28 != 0
        i = 0
        while True:
            i = 글.find(이름, i)
            if i < 0:
                break
            뒤 = i + len(이름)
            조 = 글[뒤:뒤 + 1]
            if 조 in _조사쌍:
                바름 = 조 if (받침 == (조 in ("은", "이", "을", "과"))) else _조사쌍[조]
                글 = 글[:뒤] + 바름 + 글[뒤 + 1:]
            i = 뒤
    return 글


# 사건을 한국어 한 줄로. SOCIAL_EFFECTS 와 같은 자리에 두어 게임이 함께 늘린다.
# 이 문장이 곧 그 노드를 말로 불러내는 예시가 되므로, 사람이 실제로 할 법한
# 말이어야 한다. 게임은 World(행동말=...) 로 자기 어투를 넣으면 된다.
행동말: dict[str, str] = {
    "talk": "%s가 %s에게 말을 걸었다",
    "help": "%s가 %s를 도왔다",
    "trade": "%s가 %s와 거래했다",
    "share": "%s가 %s와 나눴다",
    "threaten": "%s가 %s를 위협했다",
}


def 행동말_기본() -> dict[str, str]:
    return dict(행동말)


class World:
    """NPC 집단의 시간, 공유 상태, 사건 기록을 소유한다."""

    def __init__(self, *, state: Optional[dict[str, Any]] = None,
                 conversation_factory: Optional[Callable[[str], Any]] = None,
                 행동말: Optional[dict[str, str]] = None,
                 겪음지도: Optional[dict[str, tuple[str, str]]] = None,
                 겪음쓰기: bool = True):
        """겪음지도: 사건 종류 -> (관계, 도착노드).

        사건 자체는 이미 (주어, 종류, 목적어) 삼중항이라 캐낼 것이 없다. 다만
        그 사건이 그 NPC 의 그래프에서 '무엇을 뒷받침하는지'는 게임이 안다 —
        도움을 받으면 믿음직함으로 가는지 빚으로 가는지는 세계관의 몫이다.
        비워 두면 노드만 늘고 엣지는 안 는다.
        """
        self.tick_count = 0
        self.npcs: dict[str, NPC] = {}
        self.state: dict[str, Any] = dict(state or {})
        self.events: list[Event] = []
        self._conversation_factory = conversation_factory
        self.행동말 = dict(행동말 or 행동말_기본())
        self.겪음지도 = dict(겪음지도 or {})
        self.겪음쓰기 = 겪음쓰기

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
            if self.겪음쓰기:
                self._겪음남기기(event, npc)
        return event

    def _사건말(self, event: Event) -> Optional[str]:
        """사건 한 건을 사람이 할 법한 한 줄로. 못 만들면 None."""
        if event.text and event.kind == "speak":
            return event.text
        틀 = self.행동말.get(event.kind)
        if not 틀 or not event.target:
            return None
        보는이 = lambda i: self.npcs[i].name if i in self.npcs else i
        가, 나 = 보는이(event.actor), 보는이(event.target)
        try:
            return 조사맞추기(틀 % (가, 나), (가, 나))
        except TypeError:
            return 틀

    def _겪음남기기(self, event: Event, 목격자: NPC) -> None:
        """목격자의 그래프 옆 덧칠 파일에 이 사건을 남긴다.

        목격자에게만 쓴다. 그래서 NPC 마다 그래프가 갈라진다 — 같은 세계를
        살아도 본 것이 다르면 아는 것이 다르다. 소문·비밀·오해가 여기서 나온다.
        """
        # 그래프 파일이 없는 NPC(순수 시뮬레이션용)에게는 남기지 않는다.
        # 없는 .kg 옆에 겪음 파일만 쌓이면 아무도 읽지 않는 쓰레기가 된다.
        if not 목격자.graph_path or not os.path.exists(목격자.graph_path):
            return
        말 = self._사건말(event)
        if not 말:
            return
        이름 = "겪음_%s_%s_%s" % (event.actor, event.kind, event.target or "혼자")
        줄들: list[dict[str, Any]] = [{"노드": 이름, "층": "사례층", "말": [말]}]
        지도 = self.겪음지도.get(event.kind)
        if 지도:
            줄들.append({"엣지": [이름, 지도[0], 지도[1]]})
        경로 = os.path.splitext(목격자.graph_path)[0] + ".겪음.jsonl"
        try:
            with open(경로, "a", encoding="utf-8") as f:
                for 줄 in 줄들:
                    f.write(json.dumps(줄, ensure_ascii=False) + "\n")
        except OSError:
            pass                    # 겪음을 못 남겨도 세계는 굴러가야 한다

    def set_relationship(self, first_id: str, second_id: str, kind: str, *,
                         affinity: int = 0, trust: int = 0, fear: int = 0) -> None:
        """두 NPC의 관계 이름과 초기 감정을 함께 정한다.

        ``lover`` 같은 이름은 게임 규칙과 UI가 읽는 의미 있는 상태이고, 수치는
        행동 선택에 쓰는 연속적인 감정이다. 한쪽만 연인인 관계도 가능해야 하므로
        이후에는 각 방향의 ``relation_to(...).kind``를 따로 바꿀 수 있다.
        """
        if not kind.strip():
            raise ValueError("관계 이름이 비어 있습니다")
        first, second = self._npc(first_id), self._npc(second_id)
        if first is second:
            raise ValueError("NPC는 자기 자신과 관계를 만들 수 없습니다")
        for source, target in ((first, second), (second, first)):
            relation = source.relation_to(target.id)
            relation.kind = kind
            relation.affinity = _bounded(affinity)
            relation.trust = _bounded(trust)
            relation.fear = _bounded(fear)

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
                try:
                    actor._conversation = factory(actor.graph_path,
                                                  목소리=actor.목소리)
                except TypeError:
                    # 게임이 넣은 대화 공장이 목소리를 안 받을 수 있다.
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
                    "목소리": npc.목소리,
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
                      목소리=raw.get("목소리"),
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
