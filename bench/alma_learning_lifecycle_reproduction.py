"""Independent fixed split for concept construction, validation, application and A/B evaluation."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marco.reasoning.context import ReasoningContext


KG = ROOT / "graphs" / "graph_일상추론.kg"


def run():
    context = ReasoningContext(language="한국어")
    inputs = (
        "베풀다는 상대에게 구슬 2개를 주는 것이다.",
        "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 8개 있다. 하루 구슬은 3개 있다. 서준 구슬은 8개 있다. 유나 구슬은 3개 있다. 도윤 구슬은 8개 있다. 소라 구슬은 3개 있다. 하늘 구슬은 8개 있다. 별 구슬은 3개 있다.",
        "민수가 지연에게 베풀었다.", "가람이 하루에게 베풀었다.", "서준이 유나에게 베풀었다.")
    for text in inputs:
        context.turn(text, KG)
    before = context.snapshot()["experience_concepts"]
    context.turn("도윤이 소라에게 베풀었다.", KG)
    validated = context.snapshot()["experience_concepts"]
    candidate = next(row for row in validated["candidates"] if row["scope"]["action"] == "베풀")
    context.turn("하늘이 별에게 베풀었다.", KG)
    active = context.snapshot()["experience_concepts"]
    active_candidate = next(row for row in active["candidates"] if row["id"] == candidate["id"])
    application = next(row for row in active["applications"]
                       if row["candidate_id"] == candidate["id"] and row.get("phase") == "application")
    question = "하늘이 별에게 베푼 것은 어떤 개념이야?"
    enabled = context.turn(question, KG)
    planned = context.turn("우진이 보라에게 베풀 예정이다.", KG)
    planned_question = context.turn("우진이 보라에게 베푼 것은 어떤 개념이야?", KG)
    negative = context.turn("우진이 보라에게 베풀지 않았다.", KG)
    negative_question = context.turn("우진이 보라에게 베푼 것은 어떤 개념이야?", KG)
    conditional = context.turn("민수 구슬이 20개보다 많으면 우진이 보라에게 베풀었다.", KG)
    conditional_question = context.turn("우진이 보라에게 베푼 것은 어떤 개념이야?", KG)
    after_planned = next(row for row in context.snapshot()["experience_concepts"]["candidates"]
                         if row["id"] == candidate["id"])
    context.concepts.disabled_ids.add(candidate["id"])
    disabled = context.turn(question, KG)
    context.concepts.disabled_ids.clear()
    context.turn("정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀 예정이다.", KG)
    withdrawn = context.turn(question, KG)
    checks = [
        {"name": "construction_has_no_active_candidate", "ok": not any(
            row.get("status") == "active" for row in before["candidates"])},
        {"name": "validation_has_no_post_activation_application", "ok": candidate["support_event_ids"]
         and not candidate["application_event_ids"]},
        {"name": "lineage_is_disjoint", "ok": not (set(candidate["evidence_event_ids"]) & set(candidate["support_event_ids"])
                                                       or set(candidate["evidence_event_ids"]) & set(application["event_id"] for application in [application])
                                                       or set(candidate["support_event_ids"]) & {application["event_id"]})},
        {"name": "active_new_application", "ok": application["event_id"] in active_candidate["application_event_ids"]},
        {"name": "on_answers_application", "ok": enabled.get("status") == "answered"},
        {"name": "natural_planned_held_out_is_not_application", "ok": planned.get("status") == "observed"
         and planned_question.get("status") == "unresolved"
         and after_planned["application_event_ids"] == active_candidate["application_event_ids"]},
        {"name": "natural_negative_and_false_condition_hold_out", "ok": negative.get("status") == "observed"
         and conditional.get("status") == "observed" and negative_question.get("status") == "unresolved"
         and conditional_question.get("status") == "unresolved"
         and after_planned["application_event_ids"] == active_candidate["application_event_ids"]},
        {"name": "off_removes_only_learning_answer", "ok": disabled.get("status") == "unresolved"},
        {"name": "corrected_training_withdraws_application", "ok": withdrawn.get("status") == "unresolved"},
    ]
    return {"input_mode": "natural_language",
            "split": {"construction_event_ids": active_candidate["evidence_event_ids"],
                      "validation_event_ids": active_candidate["support_event_ids"],
                      "application_event_ids": active_candidate["application_event_ids"]},
            "functional_checks": checks,
            "independent_problems": [{"id": "new-application-concept-query", "expected": "answered",
                                      "actual": enabled.get("status"),
                                     "ok": enabled.get("status") == "answered"},
                                     {"id": "planned-new-application-holds", "expected": "unresolved",
                                      "actual": planned_question.get("status"),
                                      "ok": planned_question.get("status") == "unresolved"},
                                     {"id": "negative-new-application-holds", "expected": "unresolved",
                                      "actual": negative_question.get("status"),
                                      "ok": negative_question.get("status") == "unresolved"},
                                     {"id": "false-condition-new-application-holds", "expected": "unresolved",
                                      "actual": conditional_question.get("status"),
                                      "ok": conditional_question.get("status") == "unresolved"}],
            "outcomes": {"solved": 1 if enabled.get("status") == "answered" else 0,
                         "safe_hold": sum(result.get("status") == "unresolved" for result in (
                             planned_question, negative_question, conditional_question)),
                         "wrong": 0 if enabled.get("status") == "answered"
                         and all(result.get("status") == "unresolved" for result in (
                             planned_question, negative_question, conditional_question)) else 1,
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
