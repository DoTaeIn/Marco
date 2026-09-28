"""The seven-step dialogue through the UI's Python turn handler (AppState.turn).

Builds a pack with the reasoning graph and both language packs, selects one
language explicitly, and plays the dialogue in one conversation, then again
after restarting the app from the saved conversation store. Web research is
stubbed and counted; a call to it fails the step. Browser rendering is not
tested.
"""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(language):
    import marco.storage.kgpack as kgpack
    from marco.storage.conversations import ConversationStore
    from views.kgpack_ui import AppState
    from bench.seven_step_dialogue import SCRIPTS, _numbers
    script = SCRIPTS[language]
    rows = []
    with tempfile.TemporaryDirectory(prefix="nai-seven-ui-") as temporary:
        folder = Path(temporary)
        pack = folder / "seven.kgpack"
        kgpack.write_pack(pack, [ROOT / "graphs/graph_일상추론.kg"] + kgpack.model_files(ROOT), root=ROOT,
                          language="styles/%s.json" % language)

        def app():
            state = AppState(pack, overlay_root=folder / "overlay")
            state.conversations = ConversationStore(folder / "conversations.json")
            return state
        state = app()
        chat = state.conversations.create_chat()["id"]
        offline = {"query": "", "sources": [], "verified": False}

        def say(current, text):
            with patch.object(current.goals, "research", return_value=offline) as research:
                result = current.turn(text, "evaluation_7777", conversation_id=chat)
            answer = (result.get("answer") or {})
            rows.append({"input": text, "phase": result.get("phase"),
                         "verdict": (answer.get("trace") or {}).get("verdict"),
                         "answer": answer.get("answer"), "research_calls": research.call_count})
            return rows[-1]
        for text in script["turns"]:
            say(state, text)
        say(state, script["other_question"])
        restarted = app()
        say(restarted, script["same_question"])
        say(restarted, script["other_question"])
    expected = ["상태기억", "상태기억", "계산완료", "조건부족", "상태기억", "계산완료", "조건부족",
                "계산완료", "계산완료", "계산완료"]
    numbers = {2: ["4"], 7: ["3"], 8: ["3"], 9: ["3"]}
    for index, row in enumerate(rows):
        row["ok"] = (row["verdict"] == expected[index] and not row["research_calls"]
                     and (index not in numbers or _numbers(row["answer"]) == numbers[index]))
    return {"language": language, "passed": sum(r["ok"] for r in rows), "total": len(rows), "rows": rows}


if __name__ == "__main__":
    for language in ("english", "한국어"):
        report = run(language)
        print(language, "%d/%d" % (report["passed"], report["total"]))
        for row in report["rows"]:
            print(" ", "ok " if row["ok"] else "BAD", row["verdict"], row["input"], "->", (row["answer"] or "")[:110])
