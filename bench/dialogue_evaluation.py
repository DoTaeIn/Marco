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


def _process_peak_rss_bytes():
    """프로세스 시작 뒤의 최대 RSS. 벤치 구간만의 메모리라고 부르지 않는다."""
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, AttributeError):
        return None
    # macOS는 byte, Linux는 KiB로 준다. 다른 플랫폼은 추정하지 않는다.
    if sys.platform == "darwin":
        return int(value)
    if sys.platform.startswith("linux"):
        return int(value) * 1024
    return None


def run(dataset_path=None):
    import marco.storage.kgpack as kgpack
    from marco.storage.conversations import ConversationStore
    from views.kgpack_ui import AppState
    raw = Path(dataset_path or ROOT / "data/benchmarks/reasoning_transfer_v1.json").read_bytes()
    dataset = json.loads(raw)
    rows = []
    with tempfile.TemporaryDirectory(prefix="nai-dialogue-eval-") as temporary:
        folder = Path(temporary)
        pack = folder / "evaluation.kgpack"
        tracemalloc.start()
        start = time.perf_counter()
        kgpack.write_pack(pack, [ROOT / "graphs/graph_일상추론.kg"] + kgpack.model_files(ROOT), root=ROOT,
                          language="styles/한국어.json")
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
                # 입력 이해 실패도 안전한 보류일 수 있지만, 답 가능한 문항에서
                # 정답 대신 이를 내면 성공으로 바꾸지 않는다. ``unknown`` 표지가
                # 있는 자료에서만 적절한 보류로 센다.
                unknown = verdict in {"조건부족", "미지", "B2", "입력이해실패"} and not answer.get("known")
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
        # 시작 비용과 문제 묶음 전체 시간을 단일 턴 비용으로 부르지 않는다.
        # 위의 모든 초기화 뒤, 같은 계산을 새 세션에서 반복해 웜 응답만 잰다.
        warm_question, warm_ms = "3x + 1 = 7이래. x는 얼마야?", []
        for index in range(3):
            start = time.perf_counter()
            warm = app.turn(warm_question, "warm_eval_%03d" % index)
            warm_ms.append((time.perf_counter() - start) * 1000)
            assert warm["answer"]["answer"] == "2입니다."
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
                          "repeated_local_turn_ms_after_setup": round(statistics.median(warm_ms), 3),
                          "process_peak_rss_bytes_since_start": _process_peak_rss_bytes(),
                          "persistence_bytes_all_chats": stored_bytes},
            "resource_notes": [
                "startup_with_tracemalloc_ms includes pack creation and app initialization; it is not one answer cost.",
                "repeated_local_turn_ms_after_setup is a separate warmed local calculation.",
                "Python allocation peaks are tracemalloc values, not RSS.",
                "process_peak_rss_bytes_since_start includes imports and all benchmark work; it is not attributed to one turn.",
            ]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    report = run(args.dataset)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
