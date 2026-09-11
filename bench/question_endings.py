"""물음의 말끝을 적어 두지 않고 활용에서 만드는지 잰다.

서술문의 말끝은 오래전부터 문법으로 만들어 왔지만 물음은 빠져 있었다 —
말의 결이 바뀌는 것을 막으려고 물음을 활용 확장에서 통째로 뺐기 때문이다.
그래서 '누가 더 커?' 는 풀고 '누가 더 큰가요?' 는 못 풀었다.

``--적힌말끝만`` 은 문법에서 물음 어미 선언을 떼고 잰다. 고치기 전과 같은
자리다.
"""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATASET = ROOT / "data/benchmarks/question_endings.json"


def run(dataset_path=None, *, literal_only=False):
    from pack_model import development_model

    raw = Path(dataset_path or DATASET).read_bytes()
    dataset = json.loads(raw)
    model = development_model()
    data, language = model.relational_data, model.language
    if literal_only:
        # 고치기 전 자리 — 물음 어미 선언도 없고, 물음 예시에 활용 주석도
        # 없었다. 둘 다 떼야 같은 자리가 된다.
        language = json.loads(json.dumps(language))
        language["inflection"].pop("question_endings", None)
        data = json.loads(json.dumps(data))
        for example in data["examples"]:
            if "query" in example["meaning"]:
                example.pop("inflection", None)
    from relational_semantics import RelationalParser
    parser = RelationalParser(data=data, language_pack=language)

    rows = []
    for case in dataset["cases"]:
        try:
            parsed = parser.parse(case["text"])
            answer = (parser.answer(parsed) or {}).get("answer") if parsed else None
        except Exception:
            answer = None
        rows.append({"text": case["text"], "family": case["family"],
                     "want": case["want"], "got": answer,
                     "ok": answer == case["want"]})
    return {"dataset_sha256": hashlib.sha256(raw).hexdigest(),
            "literal_only": literal_only,
            "passed": sum(r["ok"] for r in rows), "total": len(rows), "rows": rows}


def report(result):
    by = defaultdict(lambda: [0, 0])
    for row in result["rows"]:
        by[row["family"]][0] += row["ok"]
        by[row["family"]][1] += 1
    out = ["물음 말끝 %d개%s" % (result["total"], " (적힌 말끝만)" if result["literal_only"] else ""),
           "=" * 40]
    for family, (hit, total) in by.items():
        out.append("%-10s %2d/%-3d %5.1f%%" % (family, hit, total, 100 * hit / total))
    out += ["=" * 40,
            "%-10s %2d/%-3d %5.1f%%" % ("전체", result["passed"], result["total"],
                                        100 * result["passed"] / result["total"])]
    misses = [r for r in result["rows"] if not r["ok"]]
    if misses:
        out.append("")
        out.append("놓친 것 %d개" % len(misses))
        for row in misses:
            out.append("  %-46s 나옴 %s" % (row["text"][-30:], row["got"]))
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset")
    parser.add_argument("--적힌말끝만", action="store_true", dest="literal")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = run(args.dataset, literal_only=args.literal)
    print(report(result))
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
