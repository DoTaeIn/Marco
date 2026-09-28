"""The public reproduction must fail when an expected result is wrong."""
import json
from pathlib import Path
import subprocess
import sys

import marco.reasoning.actions as action_runtime
from bench import experience_concept_reproduction
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


ROOT = Path(__file__).resolve().parents[1]


def test_experience_reproduction_rejects_an_intentionally_wrong_expected_value():
    completed = subprocess.run(
        [sys.executable, "bench/experience_concept_reproduction.py", "--expected-quantity", "999"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert completed.returncode != 0
    report = json.loads(completed.stdout)
    assert report["outcomes"]["wrong"] >= 1
    assert report["outcomes"]["execution_error"] == 0
    assert report["outcomes"]["unverifiable"] == 0


def test_experience_reproduction_rejects_a_lost_giver_decrement(monkeypatch, capsys):
    real_execute = action_runtime.execute

    def broken_execute(*args, **kwargs):
        result = real_execute(*args, **kwargs)
        # Isolated evaluator control: simulate a runtime that accidentally
        # emits a zero decrement while leaving the receiver's add intact.
        for triple in result.get("facts", []):
            if len(triple) == 3 and triple[1] == "count_remove":
                triple[2] = "0"
        return result

    monkeypatch.setattr(action_runtime, "execute", broken_execute)
    assert experience_concept_reproduction.main([]) != 0
    report = json.loads(capsys.readouterr().out)
    giver_check = next(row for row in report["checks"]
                       if row["name"] == "execution:도윤_to_소라")
    assert giver_check["bucket"] == "wrong"
    assert giver_check["evidence"]["state_changes"] != giver_check["evidence"]["expected_changes"]
    # The fixed endpoint audit keeps the premise-conflict and structural
    # controls for both domains even when this isolated execution control
    # intentionally makes the overall evaluator fail.
    checks = {row["name"]: row for row in report["checks"]}
    for name in ("quantity:premise_unknown", "quantity:conflicting_independent_premise",
                 "quantity:structural_counterexample_withdraws_relation",
                 "location:premise_unknown", "location:conflicting_independent_premise",
                 "location:structural_counterexample_withdraws_relation"):
        assert checks[name]["ok"]


def test_experience_reproduction_records_a_late_exception_in_its_output_file(monkeypatch, tmp_path, capsys):
    real_turn = experience_concept_reproduction.AppState.turn

    def broken_turn(self, text, *args, **kwargs):
        if text == "왜 그렇게 판단했어":
            raise RuntimeError("late reason failure")
        return real_turn(self, text, *args, **kwargs)

    output = tmp_path / "late-error.json"
    monkeypatch.setattr(experience_concept_reproduction.AppState, "turn", broken_turn)
    assert experience_concept_reproduction.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["stage"] == "quantity_relation_and_reason"
    assert report["outcomes"]["execution_error"] == 1
    assert any(row["name"] == "quantity_relation_and_reason" for row in report["checks"])
    json.loads(capsys.readouterr().out)
