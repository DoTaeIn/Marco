"""Offline AppState evaluation with frozen questions and isolated conversations.

The UI's Python turn handler is exercised; this does not test browser rendering.
The reasoning KG, language and axiom sources are packed. Web research is explicitly stubbed and counted,
so this measures local reasoning, not knowledge coverage or live web quality.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(dataset_path=None):
    import kgpack
    from conversation_store import ConversationStore
    from views.kgpack_ui import AppState
    raw = Path(dataset_path or ROOT / "data/benchmarks/reasoning_transfer_v1.json").read_bytes()
    dataset = json.loads(raw)
    rows = []
    with tempfile.TemporaryDirectory(prefix="nai-dialogue-eval-") as temporary:
        folder = Path(temporary)
        pack = folder / "evaluation.kgpack"
        tracemalloc.start()
        start = time.perf_counter()
        kgpack.write_pack(pack, [ROOT / "graphs/graph_일상추론.kg"] + kgpack.model_files(ROOT), root=ROOT)
        app = AppState(pack, overlay_root=folder / "overlay")
        app.conversations = ConversationStore(folder / "conversations.json")
        startup_ms = (time.perf_counter() - start) * 1000
        # Timing below is uninstrumented; memory is measured separately.
        _, startup_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        for index, case in enumerate(dataset["cases"]):
            chat = app.conversations.create_chat()["id"]
            session = f"evaluation_{index:04d}"
            # Empty web results allow the real fallback to finish without I/O.
            offline = {"query": case["input"], "sources": [], "verified": False}
            start = time.perf_counter()
            try:
                with patch.object(app.goals, "research", return_value=offline) as research:
                    result = app.turn(case["input"], session, conversation_id=chat)
                answer = result.get("answer") or {}
                text = answer.get("answer", "")
                verdict = answer.get("trace", {}).get("verdict")
                unknown = verdict in {"조건부족", "미지", "B2"} and not answer.get("known")
                correct = unknown if case.get("unknown") else text in case.get("answers", [])
                ok = bool(correct and not research.call_count and result.get("phase") == "answer")
                failure = None if ok else ("web_fallback" if research.call_count else
                                           "incorrect_or_unresolved_answer")
                row = {"answer": text, "verdict": verdict, "phase": result.get("phase"),
                       "research_calls": research.call_count, "ok": ok, "failure": failure}
                if not ok:
                    row["relation_diagnostic"] = app.model.parser().diagnose(case["input"])
            except Exception as exc:
                row = {"ok": False, "failure": "runtime_error", "error": f"{type(exc).__name__}: {exc}"}
            row.update(id=case["id"], family=case["family"],
                       elapsed_ms=round((time.perf_counter() - start) * 1000, 3))
            rows.append(row)
        tracemalloc.start()
        chat = app.conversations.create_chat()["id"]
        app.turn("돌은 23개 있다.", "memory_eval_001", conversation_id=chat)
        app.turn("돌 8개를 꺼냈다.", "memory_eval_001", conversation_id=chat)
        final = app.turn("지금 돌은 몇 개야?", "memory_eval_001", conversation_id=chat)
        _, turn_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert final["answer"]["answer"] == "15개입니다."
        stored_bytes = (folder / "conversations.json").stat().st_size
    return {"scope": "offline local reasoning via AppState; packed language + axioms + reasoning KG; no browser rendering",
            "dataset_sha256": hashlib.sha256(raw).hexdigest(), "passed": sum(r["ok"] for r in rows),
            "total": len(rows), "rows": rows,
            "resources": {"startup_with_tracemalloc_ms": round(startup_ms, 3),
                          "case_times_include_failure_diagnosis": True,
                          "startup_python_peak_bytes_excluding_imports": startup_peak,
                          "three_turn_python_peak_bytes": turn_peak,
                          "median_case_ms": statistics.median(r["elapsed_ms"] for r in rows),
                          "persistence_bytes_all_chats": stored_bytes}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    report = run(args.dataset)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
