"""Fixed outcomes for the completion-review regressions, using temporary state only."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alma.runtime import AlmaRuntime


def run():
    checks = []

    def check(name, expected, actual):
        checks.append({"name": name, "expected": expected, "actual": actual, "ok": expected == actual})

    with TemporaryDirectory(prefix="alma-regressions-") as folder:
        root = Path(folder)
        state = root / "identity.json"
        owner = AlmaRuntime(state, "agent-a"); owner.set_goal("preserve this life")
        before = state.read_bytes()
        try:
            AlmaRuntime(state, "agent-b")
        except ValueError as exc:
            identity_error = str(exc)
        else:
            identity_error = None
        check("identity_mismatch_preserves_bytes", True, identity_error == "state_identity_mismatch" and state.read_bytes() == before)

        corrupt = root / "corrupt.json"; corrupt.write_text('{"schema":', encoding="utf-8")
        before_corrupt = corrupt.read_bytes()
        try:
            AlmaRuntime(corrupt, "agent-a")
        except ValueError as exc:
            corrupt_error = str(exc)
        else:
            corrupt_error = None
        check("corrupt_state_is_not_replaced", True, corrupt_error == "state_corrupt" and corrupt.read_bytes() == before_corrupt)

        state = root / "capability.json"; runtime = AlmaRuntime(state, "agent-a"); effects = []
        runtime.register_capability({"name": "write", "permission": "write"},
                                    lambda payload: effects.append(payload) or {"ok": True})
        blocked = runtime.call_capability("write", {"id": "a"}, request_id="approval")
        approved = runtime.call_capability("write", {"id": "a"}, approved=True, request_id="approval")
        check("approved_retry_executes_once", ("approval_required", "done", 1),
              (blocked["status"], approved["status"], len(effects)))

        original_save, calls = runtime._save, []
        def interrupt_after_start():
            calls.append(True)
            if len(calls) == 1:
                original_save()
            else:
                raise OSError("interrupted_after_effect")
        with patch.object(runtime, "_save", side_effect=interrupt_after_start):
            try:
                runtime.call_capability("write", {"id": "b"}, approved=True, request_id="interrupted")
            except OSError:
                pass
        resumed = AlmaRuntime(state, "agent-a")
        resumed.adapters["write"] = lambda payload: effects.append(payload) or {"ok": True}
        unknown = resumed.call_capability("write", {"id": "b"}, approved=True, request_id="interrupted")
        check("interrupted_effect_is_held_unknown_not_reexecuted", ("unknown_execution", 2),
              (unknown["status"], len(effects)))

        resumed.turn("알 수 없는 관찰이다.", ROOT / "graphs" / "graph_일상추론.kg")
        source = resumed.snapshot()["event_index"][-1]["id"]
        goal = resumed.set_goal("안전 유지")
        resumed.assess_goal(goal["id"], threatened=False, cause_event_id=source)
        try:
            resumed.experience_preference("water", utility=1, affect_label="resolved", event_id="missing")
        except ValueError as exc:
            preference_error = str(exc)
        else:
            preference_error = None
        check("unlinked_preference_is_rejected", "unknown_preference_event", preference_error)

    return {"functional_checks": checks,
            "outcomes": {"solved": 0, "safe_hold": 0, "wrong": sum(not row["ok"] for row in checks),
                         "execution_error": 0, "unverifiable": 0}}


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report, code = run(), 0
    except Exception as exc:
        report, code = {"terminal": "execution_error", "error": repr(exc),
                        "outcomes": {"solved": 0, "safe_hold": 0, "wrong": 0,
                                     "execution_error": 1, "unverifiable": 0}}, 1
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.buffer.write(payload.encode("utf-8"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
