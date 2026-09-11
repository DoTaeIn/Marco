"""닫힌 세계(게임) 하나로 바꿔 말하기를 잰다.

고정 물음 400개는 일반 지식 그래프 905개에서 뽑은 문장이라, '그래프가 너무
많아서 31%' 인지 '바꿔 말하기를 못 따라가서 31%' 인지 가리지 못한다. 여기서는
손으로 지은 게임 세계 23개만 색인에 넣고, 그래프의 별칭을 한 글자도 베끼지
않은 플레이어 말투로 묻는다.

설명 그래프(.json)는 색인에서 뺀다 — 법지식 그래프 하나가 31MB 라 23개짜리
세계에 섞이면 무엇을 재는지 알 수 없게 된다.
"""
import argparse
import glob
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WORLD = "graphs/게임세계/*.kg"
DATASET = ROOT / "data/benchmarks/game_world_phrasing.json"


def run(dataset_path=None):
    import engine
    import routing_benchmark as bench

    raw = Path(dataset_path or DATASET).read_bytes()
    questions = json.loads(raw)["물음"]
    bodies = {p: engine.read_for_index(p)
              for p in sorted(glob.glob(str(ROOT / WORLD)))}
    bodies = {str(Path(p).relative_to(ROOT)): g for p, g in bodies.items()}
    with patch.object(engine, "find_explain_graph", return_value=[]):
        index = bench.build_index(bodies, strip=False)

    rows = []
    for item in questions:
        pick, score, cand = engine.pick_graph(item["물음"], index, count=3)
        ranked, _s, rcand = engine.pick_graph(item["물음"], index, min_n=0.0, count=3)
        rows.append({"물음": item["물음"], "want": item["그래프"],
                     "got": pick, "score": round(float(score), 3),
                     "ok": pick == item["그래프"],
                     "ranked_ok": ranked == item["그래프"],
                     "three": item["그래프"] in [n for n, _ in cand]})
    return {"dataset_sha256": hashlib.sha256(raw).hexdigest(),
            "graphs": len(bodies), "total": len(rows), "rows": rows}


def report(result):
    total = result["total"]
    ok = sum(r["ok"] for r in result["rows"])
    three = sum(r["three"] for r in result["rows"])
    ranked = sum(r["ranked_ok"] for r in result["rows"])
    unknown = sum(r["got"] is None for r in result["rows"])
    wrong = total - ok - unknown
    out = ["게임 세계 그래프 %d개 · 플레이어 물음 %d개" % (result["graphs"], total),
           "=" * 46,
           "맞는 그래프로 감      %3d/%d  %5.1f%%" % (ok, total, 100 * ok / total),
           "상위 셋 안           %3d/%d  %5.1f%%" % (three, total, 100 * three / total),
           "못 고르고 미지        %3d/%d  %5.1f%%" % (unknown, total, 100 * unknown / total),
           "틀린 그래프로 감       %3d/%d  %5.1f%%" % (wrong, total, 100 * wrong / total),
           "=" * 46,
           "문턱을 무시한 순위 1등  %3d/%d  %5.1f%%" % (ranked, total, 100 * ranked / total),
           "",
           "아래가 오늘의 천장이다 — 문턱을 어떻게 놓아도 순위를 넘지 못한다."]
    by = defaultdict(lambda: [0, 0])
    for r in result["rows"]:
        key = Path(r["want"]).stem.replace("graph_", "")
        by[key][0] += r["ok"]; by[key][1] += 1
    out += ["", "그래프별"]
    for key, (hit, n) in sorted(by.items(), key=lambda x: x[1][0] / x[1][1]):
        out.append("  %-18s %d/%d" % (key, hit, n))
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = run(args.dataset)
    print(report(result))
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
