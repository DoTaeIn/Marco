"""Removal test: delete one declared rule, the sentence that needed it must stop working.

Each case names a declaration in a language pack (an example rule by its text,
or a whole pack section), a short dialogue, and the sentence that depends on
it. With the full pack that sentence must work; with the declaration deleted
it must be unproducible or held — never still answered or recorded the same
way, and never silently carried by a neighbouring rule.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


removed_count = [0]


def _shape(row, pack):
    """Two examples are one rule when they compile to the same matcher and meaning."""
    from relational_semantics import RelationalParser
    groups = [sorted(group, key=len, reverse=True) for group in pack.get("자리조사", [])]
    patterns, meaning = RelationalParser.compile(row, pack["관계해석"].get("numerals", {}), groups,
                                                 ignore_case=bool(pack["관계해석"].get("ignore_case")))
    return (tuple(sorted(p.pattern for p in patterns)), json.dumps(meaning, sort_keys=True, ensure_ascii=False),
            json.dumps(row.get("inflection"), sort_keys=True))


def model_without(language, *, example=None, section=None, reply=None):
    """A PackModel built in memory from the source packs, one declaration removed."""
    from pack_model import PackModel, descriptor
    path = "styles/%s.json" % language
    pack = json.loads((ROOT / path).read_text(encoding="utf-8"))
    if example is not None:
        # A rule is the example's shape, not its nouns: `구슬은 18개 있다` and
        # `단추는 18개 있다` are one rule written twice. Remove every example of
        # the shape, or a twin carries the sentence and the test proves nothing.
        rows = pack["관계해석"]["examples"]
        target = next((row for row in rows if row["text"] == example), None)
        if target is None:
            raise ValueError("no example to remove: %s" % example)
        pack["관계해석"]["examples"] = [row for row in rows if _shape(row, pack) != _shape(target, pack)]
        removed_count[0] = len(rows) - len(pack["관계해석"]["examples"])
    if section is not None:
        if section not in pack:
            raise ValueError("no section to remove: %s" % section)
        del pack[section]
    assets = {path: json.dumps(pack, ensure_ascii=False).encode("utf-8")}
    for axiom in sorted((ROOT / "axioms").glob("*.json")):
        assets["axioms/" + axiom.name] = axiom.read_bytes()
    return PackModel({"version": 3, "model": descriptor(assets, path)}, assets)


CASES = [
    # (language, removed, dialogue, index of the dependent turn, what "works" means)
    ("한국어", {"example": "구슬은 18개 있다"}, ["민수는 사과 다섯 개가 있어"], 0, "observed"),
    ("한국어", {"section": "수선"}, ["민수는 사과 다섯 개가 있어"], 0, "observed"),
    ("한국어", {"example": "하루가 모래에게 2개를 줬다"},
     ["민수 사과는 5개 있다.", "지연 사과는 2개 있다.", "민수가 지연에게 두 개 줬어."], 2, "observed"),
    ("한국어", {"section": "생략"},
     ["민수는 사과 다섯 개, 지연은 두 개가 있어.", "지연 사과는 몇 개 남았어?"], 1, "answered"),
    ("한국어", {"example": "아까 준 건 2개가 아니라 1개야"},
     ["민수 사과는 5개 있다.", "지연 사과는 2개 있다.", "민수가 지연에게 사과 2개를 줬다.",
      "아까 준 건 두 개가 아니라 한 개야."], 3, "observed"),
    ("한국어", {"example": "왜 그렇게 됐어"},
     ["민수 사과는 5개 있다.", "민수 사과는 몇 개 남았어?", "왜 그렇게 됐어?"], 2, "answered"),
    ("english", {"example": "Haru has 18 marbles"}, ["Minsu has five apples."], 0, "observed"),
    ("english", {"example": "Haru gave Moru 2"},
     ["Minsu has five apples.", "Jiyeon has two apples.", "Minsu gave Jiyeon two."], 2, "observed"),
    ("english", {"section": "생략"},
     ["Minsu has five apples, and Jiyeon has two.", "How many apples does Jiyeon have?"], 1, "answered"),
    ("english", {"example": "the one given was 1, not 2"},
     ["Minsu has five apples.", "Jiyeon has two apples.", "Minsu gave Jiyeon two apples.",
      "Actually, the one given was one, not two."], 3, "observed"),
    ("english", {"example": "why did that happen"},
     ["Minsu has five apples.", "How many apples does Minsu have?", "Why did that happen?"], 2, "answered"),
]


def _play(model, turns):
    from marco.reasoning.context import ReasoningContext
    context = ReasoningContext(model=model)
    results = []
    for text in turns:
        try:
            results.append(context.turn(text) or {"status": None})
        except Exception as exc:
            results.append({"status": "error", "answer": "%s: %s" % (type(exc).__name__, exc)})
    return results


def run():
    from pack_model import development_model
    rows = []
    for language, removed, turns, index, works in CASES:
        full = _play(development_model(language), turns)[index]
        removed_count[0] = 0
        cut = _play(model_without(language, **removed), turns)[index]
        with_rule = full.get("status") == works
        # "Stops working": the dependent turn is no longer reported as that
        # outcome. For a state sentence, recording *something else* would be
        # a neighbouring rule carrying it — also a failure of this test.
        without_rule = cut.get("status") != works
        rows.append({"language": language, "removed": removed, "examples_removed": removed_count[0],
                     "sentence": turns[index],
                     "with": {"status": full.get("status"), "answer": full.get("answer")},
                     "without": {"status": cut.get("status"), "answer": cut.get("answer")},
                     "ok": with_rule and without_rule})
    return {"passed": sum(r["ok"] for r in rows), "total": len(rows), "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    report = run()
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("%d/%d" % (report["passed"], report["total"]))
    for row in report["rows"]:
        print("ok " if row["ok"] else "BAD", row["language"], row["removed"], "|", row["sentence"],
              "| with:", row["with"]["status"], "| without:", row["without"]["status"],
              (row["without"]["answer"] or "")[:90])
