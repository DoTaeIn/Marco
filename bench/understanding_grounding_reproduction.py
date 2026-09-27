"""Unknown-word grounding: the same unseen wording with the guess-and-ask path off and on.

Each case uses a wording the conversation has never seen.  ``before`` runs with
``hypothesize=False`` (the "I do not know this word" path); ``after`` lets the context
propose a known *change* that fits the sentence's slots and the current state, and ask.
The final query is scored like the other reproduction reports: ``solved`` only when the
expected value is answered, ``safe_hold`` when holding was expected and happened,
``wrong`` when a value is asserted that should not be.  ``asks`` records whether the
engine asked, so a case can also require that it did *not*.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reasoning_context import ReasoningContext

KG = str(ROOT / "graphs" / "graph_일상추론.kg")
LANGUAGE = "styles/한국어.json"

GIVE = "베풀다는 상대에게 구슬 2개를 주는 것이다."
GIVE3 = "베풀다는 상대에게 구슬 3개를 주는 것이다."
MOVE = "옮기다는 내가 물건을 서랍으로 옮기는 것이다."
PROMISE = "약속하다는 내가 상대에게 약속을 만드는 것이다."
STATE = "민수 구슬은 8개 있다. 지연 구슬은 3개 있다."
YES = "맞아"

# expected: the answer text, or None when the honest outcome is to hold.
# asks: True when the engine must ask, False when it must not, absent when either is fine.
CASES = [
    # U1: a verb taught in this conversation, met under an unseen form
    {"id": "taught-verb-unseen-form", "stage": "U1", "asks": True,
     "turns": [GIVE, STATE, "민수가 지연에게 쥐여줬다.", YES],
     "query": "지금 지연 구슬은 몇 개야?", "expected": "5개입니다."},
    {"id": "taught-verb-form-reused", "stage": "U1",
     "turns": [GIVE, STATE, "민수가 지연에게 쥐여줬다.", YES, "민수가 지연에게 쥐여줬다."],
     "query": "지금 민수 구슬은 몇 개야?", "expected": "4개입니다."},
    {"id": "taught-verb-other-people", "stage": "U1",
     "turns": [GIVE, "하루 구슬은 5개 있다. 도윤 구슬은 0개 있다.", "하루가 도윤에게 쥐여줬다.", YES],
     "query": "지금 도윤 구슬은 몇 개야?", "expected": "2개입니다."},
    {"id": "taught-place-verb", "stage": "U1",
     "turns": [MOVE, "공책은 책상에 있었다.", "하루가 공책을 치웠다.", YES],
     "query": "지금 공책은 어디에 있어?", "expected": "서랍에 있습니다."},
    {"id": "taught-relation-verb", "stage": "U1",
     "turns": [PROMISE, "민수가 지연에게 다짐했다.", YES],
     "query": "민수와 지연의 약속 상태가 어때?", "expected": "active입니다."},
    # U2: dropped particle, the pack's own verbs as candidates
    {"id": "dropped-particle", "stage": "U2", "asks": False,
     "turns": ["치우다는 내가 물건을 상자로 옮기는 것이다.", "연필은 책상에 있었다.", "하루가 연필 치웠다."],
     "query": "지금 연필은 어디에 있어?", "expected": "상자에 있습니다."},
    {"id": "pack-verb-unseen-form", "stage": "U2", "asks": True,
     "turns": ["공책은 책상에 있었다.", "하루가 공책을 서랍으로 치웠다.", YES],
     "query": "지금 공책은 어디에 있어?", "expected": "서랍에 있습니다."},
    {"id": "pack-verb-new-things", "stage": "U2",
     "turns": ["공책은 책상에 있었다.", "하루가 공책을 서랍으로 치웠다.", YES,
               "연필은 가방에 있었다.", "민수가 연필을 상자로 치웠다."],
     "query": "지금 연필은 어디에 있어?", "expected": "상자에 있습니다."},
    # U3: several changes fit; the user picks, a bare yes picks nothing
    {"id": "several-fit-yes-picks-nothing", "stage": "U3", "asks": True,
     "turns": ["민수 구슬은 8개 있다.", "민수가 구슬 3개를 뺐어.", YES],
     "query": "지금 민수 구슬은 몇 개야?", "expected": None},
    {"id": "several-fit-first-picked", "stage": "U3", "asks": True,
     "turns": ["민수 구슬은 8개 있다.", "민수가 구슬 3개를 뺐어.", "첫 번째"],
     "query": "지금 민수 구슬은 몇 개야?", "expected": "5개입니다."},
    {"id": "several-fit-second-picked", "stage": "U3", "asks": True,
     "turns": ["민수 구슬은 8개 있다.", "민수가 구슬 3개를 뺐어.", "2번"],
     "query": "지금 민수 구슬은 몇 개야?", "expected": "11개입니다."},
    # U4: the confirmed form keeps the definition it was confirmed against
    {"id": "confirmed-form-keeps-its-definition", "stage": "U4",
     "turns": [GIVE, STATE, "민수가 지연에게 쥐여줬다.", YES, GIVE3, "민수가 지연에게 쥐여줬다."],
     "query": "지금 지연 구슬은 몇 개야?", "expected": "7개입니다."},
    {"id": "taught-verb-follows-its-redefinition", "stage": "U4",
     "turns": [GIVE, STATE, "민수가 지연에게 쥐여줬다.", YES, GIVE3, "민수가 지연에게 베풀었다."],
     "query": "지금 지연 구슬은 몇 개야?", "expected": "8개입니다."},
    # U5: the thing and the amount come from the sentence
    {"id": "thing-and-amount-from-sentence", "stage": "U5", "asks": True,
     "turns": ["민수 사과는 5개 있다. 지연 사과는 1개 있다.", "민수가 지연에게 사과 3개를 쥐여줬다.", YES],
     "query": "지금 지연 사과는 몇 개야?", "expected": "4개입니다."},
    {"id": "other-thing-other-amount", "stage": "U5",
     "turns": ["민수 사과는 5개 있다. 지연 사과는 1개 있다.", "민수가 지연에게 사과 3개를 쥐여줬다.", YES,
               "민수 구슬은 9개 있다. 지연 구슬은 0개 있다.", "민수가 지연에게 구슬 4개를 쥐여줬다."],
     "query": "지금 지연 구슬은 몇 개야?", "expected": "4개입니다."},
    # U6: no known change fits; the meaning comes from the state heard afterwards
    {"id": "learned-from-observed-change", "stage": "U6", "asks": True,
     "turns": [STATE, "민수가 지연에게 구슬을 쥐여줬다.", "민수 구슬은 6개 있다. 지연 구슬은 5개 있다.", YES,
               "하루 구슬은 9개 있다. 도윤 구슬은 1개 있다.", "하루가 도윤에게 구슬을 쥐여줬다."],
     "query": "지금 도윤 구슬은 몇 개야?", "expected": "3개입니다."},
    {"id": "learned-change-other-thing", "stage": "U6",
     "turns": [STATE + " 민수 사과는 7개 있다. 지연 사과는 0개 있다.", "민수가 지연에게 구슬을 쥐여줬다.",
               "민수 구슬은 6개 있다. 지연 구슬은 5개 있다.", YES, "민수가 지연에게 사과를 쥐여줬다."],
     "query": "지금 지연 사과는 몇 개야?", "expected": "2개입니다."},
    # Counterexamples: nothing may be asserted that was not said, and most must not even ask.
    {"id": "no-slot-fits", "stage": "counter", "asks": False,
     "turns": [GIVE, STATE, "민수가 구슬을 삼켰다.", YES],
     "query": "지금 민수 구슬은 몇 개야?", "expected": None},
    {"id": "state-rejects", "stage": "counter", "asks": False,
     "turns": [GIVE, "지연 구슬은 1개 있다. 민수 구슬은 3개 있다.", "지연이 민수에게 쥐여줬다.", YES],
     "query": "지금 민수 구슬은 몇 개야?", "expected": None},
    {"id": "change-does-not-balance", "stage": "counter", "asks": False,
     "turns": [STATE, "민수가 지연에게 구슬을 쥐여줬다.", "민수 구슬은 6개 있다. 지연 구슬은 4개 있다.", YES,
               "하루 구슬은 9개 있다. 도윤 구슬은 1개 있다.", "하루가 도윤에게 구슬을 쥐여줬다."],
     "query": "지금 도윤 구슬은 몇 개야?", "expected": None},
    {"id": "someone-outside-the-sentence-changed", "stage": "counter", "asks": False,
     "turns": [STATE + " 하루 구슬은 2개 있다.", "민수가 지연에게 구슬을 쥐여줬다.",
               "민수 구슬은 6개 있다. 하루 구슬은 4개 있다.", YES,
               "도윤 구슬은 9개 있다. 가람 구슬은 1개 있다.", "도윤이 가람에게 구슬을 쥐여줬다."],
     "query": "지금 가람 구슬은 몇 개야?", "expected": None},
    {"id": "two-unread-events", "stage": "counter", "asks": False,
     "turns": [STATE, "민수가 지연에게 구슬을 쥐여줬다.", "지연이 민수에게 구슬을 떠넘겼다.",
               "민수 구슬은 6개 있다. 지연 구슬은 5개 있다.", YES,
               "하루 구슬은 9개 있다. 도윤 구슬은 1개 있다.", "하루가 도윤에게 구슬을 쥐여줬다."],
     "query": "지금 도윤 구슬은 몇 개야?", "expected": None},
]

ASKING = {"unknown_word_guess", "unknown_word_guesses"}


def _outcome(result, expected):
    status = (result or {}).get("status")
    answer = (result or {}).get("answer")
    if expected is None:
        return "safe_hold" if status != "answered" else "wrong"
    if status == "answered" and answer == expected:
        return "solved"
    return "wrong" if status == "answered" else "safe_hold"


def _run_mode(hypothesize):
    rows = []
    for case in CASES:
        context = ReasoningContext(hypothesize=hypothesize, language=LANGUAGE)
        replies = [context.turn(text, KG) for text in case["turns"]]
        result = context.turn(case["query"], KG)
        rows.append({"id": case["id"], "stage": case["stage"], "expected": case["expected"],
                     "actual": (result or {}).get("answer"), "status": (result or {}).get("status"),
                     "outcome": _outcome(result, case["expected"]),
                     "asks": any(((reply or {}).get("meaning") or {}).get("reason") in ASKING
                                 for reply in replies),
                     "must_ask": case.get("asks"),
                     "aliases": [{key: value for key, value in alias.items() if key != "유도"}
                                 for alias in context.aliases]})
    counts = {"solved": 0, "safe_hold": 0, "wrong": 0}
    for row in rows:
        counts[row["outcome"]] += 1
    return {"hypothesize": hypothesize, "outcomes": counts, "cases": rows}


def run():
    before, after = _run_mode(False), _run_mode(True)
    return {"input_mode": "natural_language_dialogue", "cases": len(CASES),
            "before": before, "after": after,
            "delta": {key: after["outcomes"][key] - before["outcomes"][key]
                      for key in ("solved", "safe_hold", "wrong")}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = run()
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
