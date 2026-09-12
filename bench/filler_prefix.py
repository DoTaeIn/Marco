"""말머리 군말이 라우팅을 얼마나 깎나.

얼린 잣대의 물음은 그래프에서 뽑은 깨끗한 문장이라 이 자리를 못 잰다.
사람은 '저기요', '죄송한데', 'ㅋㅋ 그래서' 를 앞에 붙여 말한다. 뜻은 그대로인데
포함도의 뒤쪽(물음 중 몇 할이 이 줄 안에 있나)이 깎여 점수가 내려간다.

``--군말그대로`` 는 언어팩의 군말 선언을 떼고 잰다. 고치기 전과 같은 자리다.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATASET = ROOT / "data/benchmarks/filler_prefix.json"


def run(dataset_path=None, *, keep_fillers=False):
    import engine, yardstick
    from unittest.mock import patch
    import language_components as lc

    raw = Path(dataset_path or DATASET).read_bytes()
    cases = json.loads(raw)["물음"]
    slot = yardstick.read()
    index = yardstick.index_without([x["물음"] for x in slot["안"]])

    def measure():
        bare = plain = 0
        for case in cases:
            got, _score, _cand = engine.pick_graph(case["물음"], index, count=1)
            clean, _s2, _c2 = engine.pick_graph(case["맨몸"], index, count=1)
            plain += clean == case["그래프"]
            bare += got == case["그래프"]
        return bare, plain

    if keep_fillers:
        original = lc.load_reasoning_language
        def without(language=None):
            pack = dict(original(language))
            pack["fillers"] = {}
            return pack
        with patch.object(lc, "load_reasoning_language", without):
            import encoder
            encoder._synonym_cache = None
            withfiller, clean = measure()
    else:
        withfiller, clean = measure()
    return {"dataset_sha256": hashlib.sha256(raw).hexdigest(),
            "keep_fillers": keep_fillers, "total": len(cases),
            "with_filler": withfiller, "clean": clean}


def report(r):
    t = r["total"]
    return "\n".join([
        "군말 붙은 물음 %d개%s" % (t, " (군말 선언 뗀 자리)" if r["keep_fillers"] else ""),
        "=" * 44,
        "군말 없는 맨몸        %3d/%d  %5.1f%%" % (r["clean"], t, 100 * r["clean"] / t),
        "군말 붙은 것          %3d/%d  %5.1f%%" % (r["with_filler"], t, 100 * r["with_filler"] / t),
        "=" * 44,
        "군말이 가져간 것       %3d개" % (r["clean"] - r["with_filler"]),
    ])


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--dataset")
    p.add_argument("--군말그대로", action="store_true", dest="keep")
    p.add_argument("--out")
    a = p.parse_args(argv)
    r = run(a.dataset, keep_fillers=a.keep)
    print(report(r))
    if a.out:
        Path(a.out).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
