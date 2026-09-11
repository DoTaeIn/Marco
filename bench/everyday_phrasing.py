"""실사용 말투로 입력 이해를 잰다.

같은 뜻을 사람이 쓰는 여러 말끝으로 적어 두었다. 굳은 대응표는 적힌 꼴
하나만 맞히고 나머지를 놓치므로, 이 잣대는 활용을 계산하는지 아닌지를
가른다. 대화 말은 graphs/graph_대화예절.kg 가 이미 아는 것들이다.
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATASET = ROOT / "data/benchmarks/everyday_phrasing.json"


def run(dataset_path=None, language=None):
    import input_understanding

    raw = Path(dataset_path or DATASET).read_bytes()
    dataset = json.loads(raw)
    rows = []
    for case in dataset["cases"]:
        segment = input_understanding.understand(case["text"], language=language)["segments"][0]
        best = segment["act_candidates"][0]
        reply = input_understanding.dialogue_reply(case["text"], language=language)
        rows.append({"text": case["text"], "family": case["family"],
                     "want": case["intent"], "got": best["kind"],
                     "ok": best["kind"] == case["intent"],
                     "reply": reply})
    return {"dataset_sha256": hashlib.sha256(raw).hexdigest(),
            "passed": sum(r["ok"] for r in rows), "total": len(rows), "rows": rows}


def report(result):
    by = {}
    for row in result["rows"]:
        hit, total = by.get(row["family"], (0, 0))
        by[row["family"]] = (hit + row["ok"], total + 1)
    lines = ["실사용 말투 %d개" % result["total"], "=" * 44]
    for family, (hit, total) in by.items():
        lines.append("%-10s %3d/%-3d %5.1f%%" % (family, hit, total, 100 * hit / total))
    lines.append("=" * 44)
    lines.append("%-10s %3d/%-3d %5.1f%%"
                 % ("전체", result["passed"], result["total"],
                    100 * result["passed"] / result["total"]))
    misses = [r for r in result["rows"] if not r["ok"]]
    if misses:
        lines.append("")
        lines.append("놓친 것 %d개" % len(misses))
        for row in misses:
            lines.append("  %-22s 바람 %-16s 나옴 %s" % (row["text"], row["want"], row["got"]))
    # 굳은 답이 몇 갈래인지 — 표에서 꺼내면 갈래가 적다.
    replies = Counter(r["reply"] for r in result["rows"] if r["ok"] and r["want"] == "dialogue")
    lines.append("")
    lines.append("대화 답 갈래 %d가지 / 맞힌 대화 %d개"
                 % (len(replies), sum(replies.values())))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset")
    parser.add_argument("--language")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = run(args.dataset, args.language)
    print(report(result))
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
