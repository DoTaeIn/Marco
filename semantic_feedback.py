"""Diagnose failures and publish explicitly supervised semantic corrections.

Examples:
  python semantic_feedback.py diagnose '질문'
  python semantic_feedback.py rule corrections.json --output /path/model.json
  NAI_RELATIONAL_MODEL=/path/model.json python semantic_feedback.py diagnose '질문'
"""
import argparse
import hashlib
import json
from pathlib import Path

from relational_semantics import RelationalParser


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def apply_feedback(parser, payload, kind):
    before = fingerprint(parser.data)
    if kind == "rule":
        report = parser.learn_rule(payload["corrections"], payload["validation"])
    elif kind == "expression":
        from expression_learning import propose
        report = propose(parser, payload["correction"], payload["validation"])
    elif kind == "paraphrase":
        from expression_learning import propose_paraphrase
        report = propose_paraphrase(parser, payload)
    else:
        raise ValueError("unknown_feedback_kind")
    return {**report, "before_sha256": before, "after_sha256": fingerprint(parser.data)}


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("kind", choices=("diagnose", "expression", "paraphrase", "rule"))
    args.add_argument("input", help="question for diagnose; correction JSON path otherwise")
    args.add_argument("--model", type=Path)
    args.add_argument("--output", type=Path, help="destination model; seed corpus is protected")
    options = args.parse_args()
    parser = RelationalParser(model_path=options.model)
    if options.kind == "diagnose":
        report = parser.diagnose(options.input)
    else:
        if options.output is None:
            args.error("corrections require --output")
        payload = json.loads(Path(options.input).read_text(encoding="utf-8"))
        report = apply_feedback(parser, payload, options.kind)
        if report["accepted"]:
            parser.save(options.output)
            report["saved_model"] = str(options.output.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
