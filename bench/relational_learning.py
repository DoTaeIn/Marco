"""Measure correction transfer with runtime entry points and isolated model state."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from relational_semantics import RelationalParser


def run():
    import engine
    tests = [
        ("서우는 도아에 비해 키가 크다. 도아는 라온보다 키가 크다. 서우와 라온 중 누가 더 커?", "서우입니다."),
        ("유리는 소미에 비해 키가 크다. 소미는 태오보다 키가 크다. 유리와 태오 중 누가 더 커?", "유리입니다."),
        ("루미는 다온에 비해 키가 크다. 루미와 다온 중 누가 더 커?", "루미입니다."),
    ]
    correction = {"text": "하루는 모래에 비해 키가 크다", "slots": {"a": "하루", "b": "모래"},
                  "meaning": {"triple": ["$a", "taller", "$b"]}}
    previous = os.environ.get("NAI_RELATIONAL_MODEL")
    with tempfile.TemporaryDirectory() as temporary:
        model = Path(temporary) / "model.json"
        from pack_model import development_model
        parser = development_model().parser()
        parser.save(model)
        try:
            os.environ["NAI_RELATIONAL_MODEL"] = str(model)
            before = [engine.answer(text)[2] for text, _ in tests]
            parser.learn(correction)
            parser.save(model)
            after = [engine.answer(text)[2] for text, _ in tests]
        finally:
            if previous is None:
                os.environ.pop("NAI_RELATIONAL_MODEL", None)
            else:
                os.environ["NAI_RELATIONAL_MODEL"] = previous
    return {"scope": "supervised template correction; transfer across entities and chain lengths",
            "correction": correction, "before_passed": sum(a == t[1] for a, t in zip(before, tests)),
            "after_passed": sum(a == t[1] for a, t in zip(after, tests)), "total": len(tests),
            "rows": [{"input": t[0], "before": b, "after": a} for t, b, a in zip(tests, before, after)]}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
