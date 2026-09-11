# -*- coding: utf-8 -*-
"""검증된 상태 JSON에만 적용하는 순수 상태 전이·계산기."""
from __future__ import annotations

import operator


OPERATORS = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv}


def _num(value):
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _answer(value, unit=""):
    return "%s%s입니다." % (_num(value), unit or "")


def _knowledge(knowledge):
    """KG의 공리 이름을 연산·사실 검증에 사용하는 최소 선언으로 읽는다."""
    lines = []
    if knowledge is None:
        return {"axioms": set(), "indivisible": set(), "unitary": set()}
    try:
        with open(knowledge, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return {"axioms": set(), "indivisible": set(), "unitary": set()}
    axioms, indivisible, unitary = set(), set(), set()
    section = None
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        elif section == "공리" and ":" in line:
            name = line.split(":", 1)[0].strip()
            if name.startswith("연산_"):
                axioms.add(name.removeprefix("연산_"))
            elif name.startswith("분할불가_"):
                indivisible.add(name.removeprefix("분할불가_").replace("_", ""))
            elif name.startswith("완결단위_"):
                unitary.add(name.removeprefix("완결단위_").replace("_", ""))
    return {"axioms": axioms, "indivisible": indivisible, "unitary": unitary}


def _require(knowledge, operation):
    # KG에 연산 목록이 있는 경우에는 반드시 선언돼야 한다.
    return not knowledge["axioms"] or operation in knowledge["axioms"]


def evaluate(state: dict, knowledge_path=None, *, model=None) -> dict:
    """입력 JSON을 변경하지 않으며, 답 또는 검증 실패 이유를 반환한다."""
    verification = {"accepted": bool(state.get("accepted")), "checks": [],
                    "sources": ([item["path"] for item in model.sources] if model is not None
                                else ([str(knowledge_path)] if knowledge_path is not None else []))}
    if model is not None:
        verification["model"] = model.fingerprint
        verification["model_assets"] = model.sources
    answer_value = _answer if model is None else model.number_answer
    if not state.get("accepted"):
        return {"status": "unknown", "answer": None, "operator": None, "transitions": [],
                "verification": verification | {"reason": "semantic_parse_not_certified"}}
    knowledge = _knowledge(knowledge_path)
    for relation in state.get("relations", []):
        kind, args = relation["type"], relation["args"]
        if not (model.permits(kind) if model is not None else _require(knowledge, kind)):
            verification["checks"].append({"operator": kind, "ok": False, "reason": "operator_not_declared_in_kg"}); continue
        try:
            if kind == "relational_graph":
                from relational_semantics import RelationalParser
                parser = RelationalParser() if model is None else model.parser()
                parsed = parser.parse(relation.get("evidence", {}).get("text", ""))
                if parsed != args:
                    raise ValueError("relations_not_grounded")
                outcome = parser.answer(parsed)
                if outcome is None:
                    raise ValueError("no_unique_graph_answer")
                verification["checks"].append({"operator": kind, "ok": True})
                return {"status": "answered", "operator": kind,
                        "verification": verification, **outcome}
            if kind in ("arithmetic", "linear_equation") and "expression_graph" in args:
                import expression_graph
                # Rebuild from the exact evidence instead of trusting supplied nodes.
                evidence = relation.get("evidence", {}).get("text", "")
                graph = expression_graph.parse(evidence) if model is None else model.parse_expression(evidence)
                if not graph or graph != args["expression_graph"]:
                    raise ValueError("expression_not_grounded")
                value, steps = expression_graph.solve(graph)
                verification["checks"].append({"operator": kind, "ok": True})
                return {"status": "answered", "answer": answer_value(value), "operator": kind,
                        "transitions": steps, "verification": verification}
            if kind == "arithmetic":
                op, left, right = args.get("operator"), args.get("left"), args.get("right")
                if op not in OPERATORS or isinstance(left, bool) or isinstance(right, bool) or not isinstance(left, (int, float)) or not isinstance(right, (int, float)) or (op == "/" and right == 0):
                    raise ValueError("invalid_arithmetic_operands")
                value = OPERATORS[op](left, right)
                verification["checks"].append({"operator": kind, "ok": True})
                return {"status": "answered", "answer": answer_value(_num(value)), "operator": kind,
                        "transitions": [{"before": [left, op, right], "after": value}], "verification": verification}
            if kind == "linear_equation":
                coefficient, constant, right = (args.get("coefficient"), args.get("constant"),
                                                args.get("right"))
                values = (coefficient, constant, right)
                if (any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values)
                        or coefficient == 0):
                    raise ValueError("invalid_linear_equation")
                value = (right - constant) / coefficient
                verification["checks"].append({"operator": kind, "ok": True})
                return {"status": "answered", "answer": answer_value(_num(value)), "operator": kind,
                        "transitions": [{"before": {"coefficient": coefficient, "constant": constant,
                                                       "right": right}, "after": {"x": _num(value)}}],
                        "verification": verification}
            if kind == "parallel_completion":
                duration, unit = args.get("duration"), args.get("unit")
                if not isinstance(duration, (int, float)) or not args.get("simultaneous") or not args.get("independent"):
                    raise ValueError("parallel_preconditions_missing")
                verification["checks"].append({"operator": kind, "ok": True})
                return {"status": "answered", "answer": answer_value(duration, unit), "operator": kind,
                        "transitions": [{"before": "independent jobs", "after": "same completion duration"}], "verification": verification}
            if kind == "age_difference":
                later, difference = args.get("later_age"), args.get("age_difference")
                if not isinstance(later, (int, float)) or not isinstance(difference, (int, float)):
                    raise ValueError("age_invariant_missing")
                value = later - difference
                verification["checks"].append({"operator": kind, "ok": True})
                unit = "살" if model is None else model.language["state_answers"].get("units", {}).get(kind, "")
                return {"status": "answered", "answer": answer_value(value, unit), "operator": kind,
                        "transitions": [{"before": {"later_age": later, "difference": difference}, "after": value}], "verification": verification}
            if kind == "rank_overtake":
                rank = args.get("overtaken_rank")
                if not isinstance(rank, int) or rank < 1:
                    raise ValueError("invalid_rank")
                verification["checks"].append({"operator": kind, "ok": True})
                unit = "등" if model is None else model.language["state_answers"].get("units", {}).get(kind, "")
                return {"status": "answered", "answer": answer_value(rank, unit), "operator": kind,
                        "transitions": [{"before": "behind rank %d" % rank, "after": "rank %d" % rank}], "verification": verification}
            if kind == "co_moving_reference":
                count = args.get("visible_count")
                if not isinstance(count, int) or not args.get("same_reference_frame"):
                    raise ValueError("co_moving_preconditions_missing")
                verification["checks"].append({"operator": kind, "ok": True})
                unit = "칸" if model is None else model.language["state_answers"].get("units", {}).get(kind, "")
                return {"status": "answered", "answer": answer_value(count, unit), "operator": kind,
                        "transitions": [{"before": count, "after": count, "invariant": "relative_height"}], "verification": verification}
            if kind == "indivisible_process":
                process, duration, unit = str(args.get("process") or "").replace(" ", ""), args.get("duration"), args.get("unit")
                if process not in knowledge["indivisible"] or not isinstance(duration, (int, float)) or not args.get("single_output"):
                    raise ValueError("indivisible_process_not_grounded")
                verification["checks"].append({"operator": kind, "ok": True, "fact": process})
                return {"status": "answered", "answer": answer_value(duration, unit), "operator": kind,
                        "transitions": [{"before": "single output", "after": "duration unchanged"}], "verification": verification}
            if kind == "unitary_concept":
                concept = str(args.get("concept") or "").replace(" ", "")
                if concept not in knowledge["unitary"] or not args.get("fractional_premise"):
                    raise ValueError("unitary_concept_not_grounded")
                verification["checks"].append({"operator": kind, "ok": True, "fact": concept})
                invalid = ("그 전제는 성립하지 않습니다." if model is None
                           else model.language["state_answers"].get("premise_invalid", ""))
                return {"status": "premise_invalid", "answer": invalid, "operator": kind,
                        "transitions": [], "verification": verification}
        except ValueError as exc:
            verification["checks"].append({"operator": kind, "ok": False, "reason": str(exc)})
    return {"status": "unknown", "answer": None, "operator": None, "transitions": [],
            "verification": verification | {"reason": "no_verified_generic_operator"}}
