"""Reproduce the event-ledger dialogue through the public app entry point.

This is deliberately a small, fixed evaluation fixture; development-only
cases live in ``tests/test_action_runtime.py``.  It emits the whole dialogue,
event ids, outcome buckets and process timing/memory as JSON, so no assistant
reply is used as state evidence.
"""
import json
import time
import tracemalloc
import hashlib
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

try:  # Unix-only module; Windows still reports Python allocation measurements.
    import resource
except ModuleNotFoundError:
    resource = None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kgpack
from conversation_store import ConversationStore
from marco.reasoning.inference import current_facts
from views.kgpack_ui import AppState


KG = ROOT / "graphs/graph_일상추론.kg"


def main():
    with TemporaryDirectory(prefix="nai-event-repro-") as folder:
        root = Path(folder)
        pack = root / "fixed-evaluation.kgpack"
        started = time.perf_counter()
        tracemalloc.start()
        kgpack.write_pack(pack, [KG] + kgpack.model_files(ROOT), root=ROOT, language="styles/한국어.json")
        app = AppState(pack, overlay_root=root / "overlay")
        app.conversations = ConversationStore(root / "conversations.json")
        chat = app.conversations.create_chat(title="고정 사건 평가")["id"]
        setup_finished = time.perf_counter()
        session = "fixed_event_evaluation"
        # Fixed independently from the development regressions: it exercises
        # explanation, incomplete role reply, correction, reuse and a
        # hypothetical projection through AppState rather than direct APIs.
        dialogue = [
            "베풀다는 상대에게 구슬 2개를 주는 것이다.",
            "민수 구슬은 8개 있다.",
            "지연 구슬은 3개 있다.",
            "가람 구슬은 7개 있다.",
            "지연에게 베풀었다.",
            "민수야",
            "정정: 민수 구슬은 8개 있다 => 민수 구슬은 10개 있다.",
            "민수가 가람에게 베풀었다.",
            "만약 민수가 지연에게 베풀었으면 지금 지연 구슬은 몇 개야?",
            "지금 민수 구슬은 몇 개야?",
            "지금 가람 구슬은 몇 개야?",
            "약속하다는 내가 상대에게 약속을 만드는 것이다.",
            "취소하다는 내가 상대와 약속을 취소 상태로 만드는 것이다.",
            "민수가 지연에게 약속했다.",
            "민수가 가람에게 약속했다.",
            "민수가 취소했다.",
            "지연",
            "민수와 지연의 약속 상태가 어때?",
            "민수와 가람의 약속 상태가 어때?",
        ]
        expected = {
            "지연에게 베풀었다.": "safe_hold",
            "만약 민수가 지연에게 베풀었으면 지금 지연 구슬은 몇 개야?": "7개입니다.",
            "지금 민수 구슬은 몇 개야?": "6개입니다.",
            "지금 가람 구슬은 몇 개야?": "9개입니다.",
        }
        social_expected = iter(["cancelled입니다.", "active입니다."])
        # Expected actual state after each input.  The hypothetical question
        # deliberately repeats the preceding real state.
        expected_states = [
            [], [["민수 구슬", "count", "8"]],
            [["민수 구슬", "count", "8"], ["지연 구슬", "count", "3"]],
            [["가람 구슬", "count", "7"], ["민수 구슬", "count", "8"], ["지연 구슬", "count", "3"]],
            [["가람 구슬", "count", "7"], ["민수 구슬", "count", "8"], ["지연 구슬", "count", "3"]],
            [["가람 구슬", "count", "7"], ["민수 구슬", "count", "6"], ["지연 구슬", "count", "5"]],
            [["가람 구슬", "count", "7"], ["민수 구슬", "count", "8"], ["지연 구슬", "count", "5"]],
            [["가람 구슬", "count", "9"], ["민수 구슬", "count", "6"], ["지연 구슬", "count", "5"]],
            [["가람 구슬", "count", "9"], ["민수 구슬", "count", "6"], ["지연 구슬", "count", "5"]],
            [["가람 구슬", "count", "9"], ["민수 구슬", "count", "6"], ["지연 구슬", "count", "5"]],
            [["가람 구슬", "count", "9"], ["민수 구슬", "count", "6"], ["지연 구슬", "count", "5"]],
            [["가람 구슬", "count", "9"], ["민수 구슬", "count", "6"], ["지연 구슬", "count", "5"]],
            [["가람 구슬", "count", "9"], ["민수 구슬", "count", "6"], ["지연 구슬", "count", "5"]],
            [["가람 구슬", "count", "9"], ["민수", "promise_status", "지연"], ["민수 구슬", "count", "6"], ["지연 구슬", "count", "5"]],
            [["가람 구슬", "count", "9"], ["민수", "promise_status", "지연"], ["민수 구슬", "count", "6"], ["지연 구슬", "count", "5"]],
            [["가람 구슬", "count", "9"], ["민수", "promise_status", "취소 지연"], ["민수 구슬", "count", "6"], ["지연 구슬", "count", "5"]],
            [["가람 구슬", "count", "9"], ["민수", "promise_status", "취소 지연"], ["민수 구슬", "count", "6"], ["지연 구슬", "count", "5"]],
        ]
        # The Social tail intentionally branches by relationship identity,
        # not by a single per-person status slot.  Keep the pre-Social fixed
        # evaluation states above and replace its old compatibility tail.
        quantity_states = expected_states[:11]
        base = [["가람 구슬", "count", "9"], ["민수 구슬", "count", "6"],
                ["지연 구슬", "count", "5"]]
        active_j = base + [["민수 promise 지연", "relation_status", "active"]]
        active_both = active_j + [["민수 promise 가람", "relation_status", "active"]]
        cancelled_j = base + [["민수 promise 지연", "relation_status", "cancelled"],
                              ["민수 promise 가람", "relation_status", "active"]]
        expected_states = quantity_states + [base, base, active_j, active_both,
                                             active_both, cancelled_j, cancelled_j,
                                             cancelled_j]
        rows, counts = [], {"solved": 0, "safe_hold": 0, "wrong": 0, "execution_error": 0}
        for position, text in enumerate(dialogue):
            before = time.perf_counter()
            try:
                response = app.turn(text, session, conversation_id=chat)
                answer = response["answer"]
                status = answer.get("trace", {}).get("verdict", response.get("phase"))
                bucket = "safe_hold" if status == "조건부족" else "solved"
                wanted = (next(social_expected) if text.startswith("민수와 ")
                          else expected.get(text))
                if wanted and wanted != "safe_hold" and answer.get("answer") != wanted:
                    bucket = "wrong"
                context = app.reasoning_contexts.get("chat_" + chat)
                replay = context.snapshot().get("replay", {}) if context else {}
                state, _changes = current_facts(replay.get("facts", []),
                                                context._parser().data.get("mutable_predicates", []),
                                                context._parser().data.get("numeric_updates", {})) if context else ([], [])
                actual_state = sorted([row["triple"] for row in state])
                expected_state = sorted(expected_states[position])
                if actual_state != expected_state:
                    bucket = "wrong"
                counts[bucket] += 1
                rows.append({"input": text, "phase": response.get("phase"),
                             "answer": answer.get("answer"), "expected": wanted,
                             "expected_state": expected_state, "actual_state": actual_state,
                             "bucket": bucket,
                             "elapsed_ms": round((time.perf_counter() - before) * 1000, 3)})
            except Exception as exc:  # a repro report must count, not hide, failures
                counts["execution_error"] += 1
                rows.append({"input": text, "bucket": "execution_error", "error": repr(exc)})
        # Restart the actual public app, then apply a further event to the
        # saved conversation.  This is deliberately separate from the main
        # fixed dialogue timing so setup/restart costs are visible.
        restart_started = time.perf_counter()
        restarted = AppState(pack, overlay_root=root / "overlay-restarted")
        restarted.conversations = ConversationStore(root / "conversations.json")
        continued = restarted.turn("민수가 지연에게 베풀었어.", "fixed_event_restarted",
                                   conversation_id=chat)
        continued_answer = restarted.turn("지금 지연 구슬은 몇 개야?", "fixed_event_restarted",
                                          conversation_id=chat)
        restart_report = {
            "event_phase": continued.get("phase"),
            "expected_answer": "7개입니다.",
            "actual_answer": continued_answer["answer"]["answer"],
            "replay_scope": continued_answer["answer"]["verification"]["replay_scope"],
            "elapsed_ms": round((time.perf_counter() - restart_started) * 1000, 3),
        }
        state = restarted.conversations.reasoning_state(chat)
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        process_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else None
        # macOS reports bytes; Linux reports KiB.  Keep the raw value too so
        # the report remains auditable on either execution host.
        process_rss_bytes = (process_rss if sys.platform == "darwin" else process_rss * 1024) if process_rss is not None else None
        total_finished = time.perf_counter()
        report = {
            "environment": {"python": __import__("sys").version.split()[0], "pack": str(pack),
                            "pack_sha256": hashlib.sha256(pack.read_bytes()).hexdigest(),
                            "kg": str(KG), "conversation_id": chat,
                            "model_assets": app.model.sources,
                            "git_revision": subprocess.run(
                                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                capture_output=True, check=True).stdout.strip(),
                            "worktree_status": subprocess.run(
                                ["git", "status", "--short"], cwd=ROOT, text=True,
                                capture_output=True, check=True).stdout.splitlines()},
            "dialogue": rows, "outcomes": counts,
            "restored_new_event": restart_report,
            "event_ids": [row["event"]["id"] for row in state.get("events", [])],
            "event_records": state.get("events", []),
            "event_revisions": state.get("event_revisions", []),
            "inference_bundles": state.get("inference_bundles", {}),
            "snapshot_schema": state.get("schema"),
            "initial_setup_ms": round((setup_finished - started) * 1000, 3),
            "repeat_execution": {"turn_count": len(rows),
                                 "total_ms": round(sum(row.get("elapsed_ms", 0) for row in rows), 3),
                                 "mean_ms": round(sum(row.get("elapsed_ms", 0) for row in rows) / len(rows), 3)},
            "total_reproduction_ms": round((total_finished - started) * 1000, 3),
            "tracemalloc_peak_bytes": peak,
            "process_max_rss": {"raw": process_rss, "bytes": process_rss_bytes,
                                "supported": resource is not None},
        }
        # stdout must also be readable through a legacy Windows text pipe.
        sys.stdout.write(json.dumps(report, ensure_ascii=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
