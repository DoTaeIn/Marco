import json
from pathlib import Path
import subprocess
import sys

from alma.runtime import AlmaRuntime
from bench.alma_environment_reproduction import scenario
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


KG = "graphs/graph_일상추론.kg"


def test_cli_exposes_durable_ledger_search(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "cli-agent")
    runtime.turn("민수 구슬은 8개 있다.", KG)
    command = [sys.executable, "alma/cli.py", "--state", str(state), "--identity", "cli-agent",
               "--search", "민수", "--search-kinds", "log"]
    result = subprocess.run(command, cwd=Path.cwd(), check=True, capture_output=True, text=True, encoding="utf-8")
    rows = json.loads(result.stdout)
    assert rows and all(row["kind"] == "log" for row in rows)


def test_cli_backup_keeps_personal_life_separate_from_its_original_state(tmp_path):
    state, backup = tmp_path / "alma.json", tmp_path / "backup.json"
    runtime = AlmaRuntime(state, "cli-agent")
    runtime.set_goal("관계 유지")
    command = [sys.executable, "alma/cli.py", "--state", str(state), "--identity", "cli-agent",
               "--backup-state", str(backup)]
    result = subprocess.run(command, cwd=Path.cwd(), check=True, capture_output=True, text=True, encoding="utf-8")
    receipt = json.loads(result.stdout)
    assert receipt["path"] == str(backup) and receipt["sha256"]
    assert AlmaRuntime(backup, "cli-agent").snapshot()["goals"][0]["goal"] == "관계 유지"


def test_cli_restores_personal_state_from_a_pack_in_a_clean_working_directory(tmp_path):
    import marco.storage.kgpack as kgpack
    clean = tmp_path / "clean"; clean.mkdir()
    pack, life, backup = clean / "knowledge.kgpack", clean / "life.json", clean / "life-backup.json"
    kgpack.write_pack(pack, [Path(KG)] + kgpack.model_files(Path.cwd()), root=Path.cwd())
    base = [sys.executable, str(Path.cwd() / "alma/cli.py"), "--pack", str(pack),
            "--state", str(life), "--identity", "packed-agent"]
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다.",
                 "민수가 지연에게 베풀었다."):
        subprocess.run(base + ["--turn", text], cwd=clean, check=True,
                       capture_output=True, text=True, encoding="utf-8")
    subprocess.run(base + ["--backup-state", str(backup)], cwd=clean, check=True,
                   capture_output=True, text=True, encoding="utf-8")
    resumed = subprocess.run([*base[:4], "--state", str(backup), "--identity", "packed-agent",
                              "--turn", "지금 지연 구슬은 몇 개야?"], cwd=clean, check=True,
                             capture_output=True, text=True, encoding="utf-8")
    assert json.loads(resumed.stdout)["answer"] == "5개입니다."


def test_cli_starts_and_resumes_the_local_environment(tmp_path):
    state, environment = tmp_path / "alma.json", tmp_path / "environment.json"
    environment.write_text(json.dumps(scenario(), ensure_ascii=False), encoding="utf-8")
    base = [sys.executable, "alma/cli.py", "--state", str(state), "--identity", "cli-agent",
            "--environment", str(environment)]
    paused = subprocess.run(base + ["--step-budget", "1"], cwd=Path.cwd(), check=True,
                           capture_output=True, text=True, encoding="utf-8")
    run_id = json.loads(paused.stdout)["id"]
    resumed = subprocess.run(base + ["--resume-environment", run_id, "--step-budget", "4"],
                              cwd=Path.cwd(), check=True, capture_output=True, text=True, encoding="utf-8")
    assert json.loads(resumed.stdout)["status"] == "completed"


def test_cli_projects_a_timed_personal_state(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "cli-agent")
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다.",
                 "민수가 지연에게 베풀었다."):
        runtime.turn(text, KG)
    event = next(row for row in runtime.snapshot()["event_index"]
                 if row["execution_status"] == "executed")
    runtime.annotate_event(event["id"], effective_at=2)
    command = [sys.executable, "alma/cli.py", "--state", str(state), "--identity", "cli-agent",
               "--project-state-at", "2"]
    result = subprocess.run(command, cwd=Path.cwd(), check=True, capture_output=True, text=True, encoding="utf-8")
    values = {(row["subject"], row["predicate"]): row["value"]
              for row in json.loads(result.stdout)["state"]}
    assert values[("민수 구슬", "count")] == 6


def test_cli_evaluates_a_structured_mental_event_condition(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "cli-agent")
    runtime.turn("알 수 없는 관찰값이다.", KG)
    source = runtime.snapshot()["event_index"][0]["id"]
    runtime.update_mental("민지", "expectation", ["책", "location", "서랍"], modality="conditional",
                          conditions=[{"event_id": source}])
    command = [sys.executable, "alma/cli.py", "--state", str(state), "--identity", "cli-agent",
               "--mental-holder", "민지", "--mental-kind", "expectation",
               "--mental-condition-event", source]
    result = subprocess.run(command, cwd=Path.cwd(), check=True, capture_output=True, text=True, encoding="utf-8")
    answer = json.loads(result.stdout)
    assert answer["status"] == "answered" and answer["world_asserted"] is False
