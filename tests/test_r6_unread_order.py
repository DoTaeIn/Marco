"""W5-3 (b), G6.7: the unread statement a hold names is a function of the conversation only.

Two unread statements block a question, each through a different key of the question (the
holder, and the count asked). The hold names the earlier of the two in the conversation's order:
the same statements in the other order name the other one, and the hash seed changes nothing.
"""
import os
from pathlib import Path
import subprocess
import sys

from pack_model import development_model
from reasoning_context import ReasoningContext

ROOT = Path(__file__).resolve().parents[1]
ORDERS = {
    "english": (["Quill has 7 tacks and Rook has 2.", "Rook zorped three tacks.", "Quill has 9 tacks.",
                 "Quill blorped two tacks.", "How many tacks does Quill have?"],
                ["Quill has 7 tacks and Rook has 2.", "Quill blorped two tacks.", "Rook has 9 tacks.",
                 "Rook zorped three tacks.", "How many tacks does Quill have?"]),
    "한국어": (["퀼은 압정이 7개 있고 룩은 2개 있어.", "룩이 압정 세 개를 조르프했어.", "퀼은 압정이 9개 있어.",
               "퀼이 압정 두 개를 블로프했어.", "퀼은 압정이 몇 개 있어?"],
              ["퀼은 압정이 7개 있고 룩은 2개 있어.", "퀼이 압정 두 개를 블로프했어.", "룩은 압정이 9개 있어.",
               "룩이 압정 세 개를 조르프했어.", "퀼은 압정이 몇 개 있어?"]),
}


def named(language, lines):
    other = "english" if language == "한국어" else "한국어"
    context = ReasoningContext(model=development_model(language), companions=[development_model(other)])
    rows = [context.turn(line) or {} for line in lines]
    meaning = rows[-1].get("meaning") or {}
    return meaning.get("reason"), meaning.get("said")


def test_the_hold_names_the_earliest_unread_statement_in_either_order():
    for language, orders in ORDERS.items():
        for lines in orders:
            assert named(language, lines) == ("unread_event", lines[1]), (language, lines)


def test_the_named_statement_does_not_follow_the_hash_seed():
    script = ("import json, sys; from tests.test_r6_unread_order import ORDERS, named; "
              "print(json.dumps([named(k, lines) for k, orders in ORDERS.items() for lines in orders]))")
    said = set()
    for seed in ("0", "2"):          # on main these two seeds named different statements
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONIOENCODING="utf-8", PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout
        said.add(out.strip().splitlines()[-1])
    assert len(said) == 1
