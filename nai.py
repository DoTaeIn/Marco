# -*- coding: utf-8 -*-
"""게임과 문서 대화가 함께 쓰는 지식 그래프 진입점.

지식은 그래프에, 대화 상태는 이 객체에 둔다. 호출자는 그래프가 판정형(.kg)인지
문서형(.json)인지 알 필요 없이 ``Conversation(...).reply(말)``만 호출한다.

    python nai.py --build data/법지식 --out data/법지식/지식그래프.json
    python nai.py graphs/graph_의료.kg --ask "어떤 증거가 필요해?"
    python nai.py data/법지식/지식그래프.json --chat
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class Reply:
    """한 턴의 공통 결과.

    ``intent``는 사용자가 바라는 답의 모양(정의·방법·경로 등) 또는 게임의
    판정(인정·되묻기 등)이다. ``topic``과 ``path``는 답이 지도 어디에서
    나왔는지 보여 주므로, UI는 이 값만으로 근거 경로를 강조할 수 있다.
    """

    text: str
    intent: str
    topic: Optional[str]
    path: list[str]
    status: Optional[str] = None


def build_graph(source: str | os.PathLike[str], output: str | os.PathLike[str], *, minimum: int = 2) -> dict[str, Any]:
    """텍스트/Markdown 폴더를 설명형 지식 그래프로 만든다.

    생성은 기존 ``build.py`` 한 곳에 맡긴다. 이 함수는 입력을 모으고 결과를
    저장할 뿐이므로, 게임용 KG 저작 형식과 문서형 자동 생성 형식이 섞이지 않는다.
    """
    from build import 짓기

    root = Path(source)
    if not root.is_dir():
        raise ValueError("그래프로 만들 입력 폴더가 아닙니다: %s" % root)
    files = sorted(p for p in root.rglob("*")
                   if p.is_file() and p.suffix.lower() in (".txt", ".md")
                   and not p.name.lower().startswith(("readme", "_", ".")))
    if not files:
        raise ValueError("%s 안에 지식으로 쓸 .txt 또는 .md 파일이 없습니다" % root)
    graph = 짓기([str(p) for p in files], 최소=minimum)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return graph


class Conversation:
    """그래프 하나를 자연스러운 여러 턴 대화로 여는 공통 세션."""

    def __init__(self, graph_path: str | os.PathLike[str], mode: Optional[str] = None):
        self.path = str(graph_path)
        suffix = Path(graph_path).suffix.lower()
        self.mode = mode or ("game" if suffix == ".kg" else "guide")
        if self.mode not in ("game", "guide"):
            raise ValueError("mode는 game 또는 guide여야 합니다")

        if self.mode == "game":
            import engine
            self.graph = engine.load(self.path)
            self._engine = engine
            self._session = engine.세션(self.graph)
            self._memory = None
        else:
            import explain
            self.graph = explain.열기(self.path)
            self._engine = explain
            self._memory = explain.대화기억()
            self._session = None

    def _game_path(self, topic: Optional[str]) -> list[str]:
        """주장에서 목표까지 실제 전진 관계로 닿는 가장 짧은 길."""
        if not topic:
            return []
        goal = self.graph["목표"]
        queue = [(topic, [topic])]
        seen = {topic}
        while queue:
            node, route = queue.pop(0)
            if node == goal:
                return route
            for relation, nxt in self.graph["adj"].get(node, ()):
                if relation in self._engine.POS and nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, route + [nxt]))
        return []

    def reply(self, text: str) -> Reply:
        """입력의 의도와 주제를 찾고, 그래프가 뒷받침하는 말만 돌려준다."""
        text = text.strip()
        if not text:
            return Reply("말씀을 한 문장으로 남겨 주십시오.", "empty", None, [])

        if self.mode == "game":
            tag, answer, outcome = self._session.말하기(text)
            plan = self._session.계획
            # 미지/B2에서 engine은 다음 판단을 위해 가장 가까운 후보를 계산할 수
            # 있다. 그 후보는 답의 근거가 아니므로 공통 API 밖으로 새면 안 된다.
            topic = (plan.get("주장") or plan.get("근거")) if tag not in ("미지", "B2") else None
            return Reply(answer, tag, topic, self._game_path(topic), outcome)

        intent, answer, topic = self._engine.물어보기(self.graph, text, self._memory)
        # 설명 엔진은 기억을 외부에서 한 턴씩 갱신하게 설계되어 있다. 공통 API가
        # 그 책임을 가져야 후속 질문("그건 왜?")도 모든 사용자에게 작동한다.
        topics = [topic] if topic else []
        self._memory.한턴(topics, text, topic)
        return Reply(answer or "그래프에서 근거를 찾지 못했습니다.", intent, topic, [topic] if topic else [])

    def state(self) -> dict[str, Any]:
        """UI/게임이 다음 선택지를 표시할 때 쓰는, 생성하지 않은 대화 상태."""
        if self.mode == "game":
            return {"mode": "game", "turn": self._session.회차,
                    "outcome": self._session.결과(), "requirements": self._session.현황()}
        return {"mode": "guide", "turn": self._memory.turn,
                "active_topics": self._memory.뜨거운()}


def _main() -> int:
    parser = argparse.ArgumentParser(description="공통 지식 그래프 대화 기반")
    parser.add_argument("graph", nargs="?", help=".kg 또는 설명형 .json 그래프")
    parser.add_argument("--build", metavar="FOLDER", help="문서 폴더에서 설명형 그래프 생성")
    parser.add_argument("--out", help="--build 결과 파일")
    parser.add_argument("--min", type=int, default=2, help="그래프 생성 최소 개념 빈도")
    parser.add_argument("--ask", help="한 번만 묻고 JSON 결과 출력")
    parser.add_argument("--chat", action="store_true", help="종료 입력까지 대화")
    args = parser.parse_args()

    if args.build:
        output = args.out or str(Path(args.build) / "지식그래프.json")
        graph = build_graph(args.build, output, minimum=args.min)
        print("문서 그래프 생성: 노드 %d · 엣지 %d -> %s" % (len(graph["노드"]), len(graph["엣지"]), output))
        return 0
    if not args.graph:
        parser.error("그래프를 지정하거나 --build <폴더>를 사용하십시오")

    chat = Conversation(args.graph)
    if args.ask is not None:
        print(json.dumps(asdict(chat.reply(args.ask)), ensure_ascii=False, indent=2))
        return 0
    if not args.chat:
        parser.error("--ask 또는 --chat이 필요합니다")
    print("[%s] 종료하려면 빈 줄 또는 '종료'를 입력하십시오." % chat.mode)
    while True:
        try:
            question = input("> ").strip()
        except EOFError:
            break
        if question in ("", "종료", "q"):
            break
        reply = chat.reply(question)
        print(reply.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
