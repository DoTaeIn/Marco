# -*- coding: utf-8 -*-
"""가벼움은 주장이 아니라 성질이다 — 여기서 지키는 것은 잴 수 있는 쪽이다.

시간·메모리 수치는 기계마다 달라 시험에 못 박지 않는다(그 값은
`docs/ko/가벼움-측정.md` 에 적는다). 여기서는 흔들리지 않는 셋만 지킨다:
망을 안 타는가, 안 고른 부품을 안 불러오는가, 기본 경로가 제삼자 꾸러미에
기대지 않는가.
"""
import json
import socket
import subprocess
import sys
from pathlib import Path
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default

ROOT = Path(__file__).resolve().parents[1]
KG = "graphs/graph_일상추론.kg"


def test_a_local_answer_opens_no_socket(monkeypatch):
    attempts = []

    class Blocked(socket.socket):
        def connect(self, address):
            attempts.append(address)
            raise OSError("이 시험에서는 망을 쓰지 않는다")

    monkeypatch.setattr(socket, "socket", Blocked)
    from marco.reasoning.context import ReasoningContext
    context = ReasoningContext()
    for text in ("민수 구슬은 8개 있다.", "민수 구슬 2개를 꺼냈다.", "지금 민수 구슬은 몇 개야?"):
        result = context.turn(text, KG)
    assert result["answer"] == "6개입니다."
    assert attempts == []


def test_a_component_is_imported_only_when_the_pack_chooses_it():
    """고르지 않은 부품은 **불러오지도** 않는다. 고르면 그때 불러온다."""
    program = (
        "import sys, json\n"
        "from pack_model import PackModel, descriptor\n"
        "import marco.language.passage_components as pc\n"
        "def pack(choice=None):\n"
        "    lang = json.load(open('styles/한국어.json', encoding='utf-8'))\n"
        "    if choice: lang['부품'] = {pc.KIND: choice}\n"
        "    a = {'styles/x.json': json.dumps(lang, ensure_ascii=False).encode(),\n"
        "         'axioms/core.json': open('axioms/core.json','rb').read()}\n"
        "    return PackModel({'version':3,'model':descriptor(a)}, a)\n"
        "pc.resolve_backend(model=pack())\n"
        "before = 'marco.language.passages' in sys.modules\n"
        "pack('marco.language.passages:LabelLearnedClassifier').component(pc.KIND)\n"
        "after = 'marco.language.passages' in sys.modules\n"
        "print(before, after)\n"
    )
    out = subprocess.run([sys.executable, "-c", program], cwd=ROOT, capture_output=True,
                         text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["False", "True"], out.stdout


def test_the_default_path_pulls_in_no_third_party_package():
    """기본 실행이 제삼자 꾸러미를 안 쓰면 설치 없이 그대로 돈다."""
    program = (
        "import sys\n"
        "base = set(sys.modules)\n"
        "from marco.reasoning.context import ReasoningContext\n"
        "c = ReasoningContext()\n"
        "c.turn('민수 구슬은 8개 있다.', 'graphs/graph_일상추론.kg')\n"
        "c.turn('지금 민수 구슬은 몇 개야?', 'graphs/graph_일상추론.kg')\n"
        "import pathlib\n"
        "added = {m.split('.')[0] for m in set(sys.modules) - base}\n"
        "outside = sorted(m for m in added\n"
        "                 if m not in sys.stdlib_module_names and not m.startswith('_')\n"
        "                 and not (pathlib.Path(m + '.py').is_file() or pathlib.Path(m).is_dir()))\n"
        "print(','.join(outside))\n"
    )
    out = subprocess.run([sys.executable, "-c", program], cwd=ROOT, capture_output=True,
                         text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", out.stdout
