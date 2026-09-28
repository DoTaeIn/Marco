"""Tests for the public ``mco`` package (API, formats, backends, CLI).

The runtime tests compile a two-graph model from this checkout, so they
exercise the real MARCO engine through the compatibility backend.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

import mco
from mco.backends import Backend, BackendModel, BackendSession, register_backend
from mco.backends import _registered as registered_backends
from mco.backends.marco import translate
from mco.formats import NATIVE_MAGIC, detect

ROOT = Path(__file__).resolve().parents[1]
GRAPHS = ["graphs/graph_정산_나눠내기.kg", "graphs/graph_일상추론.kg"]
# A Korean model names its language: English is the declared default
# (tests/test_repair_and_english.py::test_english_is_the_one_declared_default).
LANGUAGE = "styles/한국어.json"

# Korean input and a Korean pack: name the language instead of relying on
# whichever pack happens to be selected.
pytestmark = pytest.mark.language("한국어")


@pytest.fixture(scope="module")
def model_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("mco") / "MARCO-1.mco"
    report = mco.compile(ROOT, out, graphs=GRAPHS, name="MARCO-1", language=LANGUAGE)
    assert report.output == str(out)
    return out


@pytest.fixture(scope="module")
def model(model_path: Path):
    with mco.load(model_path) as loaded:
        yield loaded


# --- separation -----------------------------------------------------------------

def test_import_and_inspect_do_not_import_marco(model_path: Path) -> None:
    code = ("import sys, mco; info = mco.inspect(sys.argv[1]); "
            "leaked = [m for m in ('engine', 'kgpack', 'pack_model', 'views.kgpack_ui') if m in sys.modules]; "
            "print(info.format, leaked)")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    out = subprocess.run([sys.executable, "-c", code, str(model_path)], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert out == "mco-compat []"


def test_public_modules_never_import_marco_names() -> None:
    marco_modules = {"engine", "kgpack", "pack_model", "views", "encoder", "conversation_store"}
    for path in (ROOT / "mco").rglob("*.py"):
        if path.name == "marco.py":
            continue  # the compatibility backend is the one allowed bridge
        text = path.read_text(encoding="utf-8")
        for name in marco_modules:
            assert f"import {name}" not in text and f"from {name} " not in text, (path, name)


# --- result types ------------------------------------------------------------------

def test_result_contract() -> None:
    result = mco.Result(answer="ok", status="answered",
                        evidence=[mco.Evidence("fact", "a", source="s", detail={"x": [1]})],
                        trace=[mco.TraceStep("judge", "done")])
    assert result.status is mco.Status.ANSWERED and result.status == "answered"
    assert str(result.status) == "answered" and str(result) == "ok" and result.ok
    assert str(result.evidence) == "1. [fact] a @ s"
    assert result.trace.stage("judge").summary == "done"
    assert json.loads(result.to_json())["evidence"][0]["detail"] == {"x": [1]}
    with pytest.raises(TypeError):
        result.evidence[0].detail["x"] = 2  # type: ignore[index]
    with pytest.raises(AttributeError):
        result.answer = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError):
        mco.Result(answer="", status="maybe")


def test_reasoning_input_validation() -> None:
    data = mco.ReasoningInput.coerce({"facts": ["a", {"subject": "s", "predicate": "p", "value": 1}],
                                      "question": "q"})
    assert [f.structured for f in data.facts] == [False, True]
    assert mco.ReasoningInput.coerce(["a"]).question is None
    for bad in ("text", {"facts": "a"}, {"facts": [], "question": None}, {"other": 1},
                {"facts": [{"value": 1}]}, {"facts": [""]}, 5):
        with pytest.raises(mco.InvalidInputError):
            mco.ReasoningInput.coerce(bad)  # type: ignore[arg-type]


# --- formats -------------------------------------------------------------------------

def test_inspect_reports_model(model_path: Path) -> None:
    info = mco.inspect(model_path)
    assert (info.format, info.format_version, info.name, info.backend) == ("mco-compat", 0, "MARCO-1", "marco-kgpack")
    assert info.graphs == 2 and info.verified and info.runnable
    assert info.language == "styles/한국어.json" and info.supports(mco.Capability.MULTI_TURN)
    assert not info.supports(mco.Capability.STRUCTURED_FACTS)
    assert any("not MCO Format 1" in n for n in info.notes)


def test_fingerprint_matches_marco(model_path: Path) -> None:
    import marco.storage.kgpack as kgpack
    from pack_model import PackModel
    payload = model_path.parent / "fp.kgpack"
    payload.write_bytes(detect(model_path).payload_bytes())
    manifest, data = kgpack.read(payload)
    assert mco.inspect(model_path).fingerprint == PackModel(manifest, data).fingerprint


def test_compile_is_deterministic_and_wraps_packs(model_path: Path, tmp_path: Path) -> None:
    again = tmp_path / "again.mco"
    mco.compile(ROOT, again, graphs=GRAPHS, name="MARCO-1", language=LANGUAGE)
    assert again.read_bytes() == model_path.read_bytes()
    pack = tmp_path / "bare.kgpack"
    pack.write_bytes(detect(model_path).payload_bytes())
    assert mco.inspect(pack).format == "kgpack"
    wrapped = mco.compile(pack, tmp_path / "wrapped.mco", name="MARCO-1")
    assert wrapped.info.build_id == mco.inspect(model_path).build_id


def test_compile_errors(tmp_path: Path) -> None:
    with pytest.raises(mco.ModelNotFoundError):
        mco.compile(tmp_path / "missing", tmp_path / "x.mco")
    with pytest.raises(mco.CompileError):
        mco.compile(ROOT, tmp_path / "x.mco", graphs=["graphs/does-not-exist-*.kg"])
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(mco.CompileError):
        mco.compile(empty, tmp_path / "x.mco")


def _rewrite(src: Path, dst: Path, change) -> Path:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for name in zin.namelist():
            zout.writestr(name, change(name, zin.read(name)))
    return dst


def test_damaged_files_are_rejected(model_path: Path, tmp_path: Path) -> None:
    with pytest.raises(mco.ModelNotFoundError):
        mco.load(tmp_path / "nope.mco")
    with pytest.raises(mco.ModelFormatError):
        mco.inspect(tmp_path)  # a directory
    truncated = tmp_path / "truncated.mco"
    truncated.write_bytes(model_path.read_bytes()[:500])
    with pytest.raises(mco.ModelFormatError):
        mco.inspect(truncated)
    garbage = tmp_path / "garbage.mco"
    garbage.write_bytes(b"hello world")
    with pytest.raises(mco.ModelFormatError):
        mco.inspect(garbage)

    def flip_payload(name, body):
        if name != "payload.kgpack":
            return body
        inner = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(body)) as zin, zipfile.ZipFile(inner, "w") as zout:
            for n in zin.namelist():
                data = zin.read(n)
                zout.writestr(n, data + b"\n" if n.endswith(".kg") else data)
        return inner.getvalue()
    tampered = _rewrite(model_path, tmp_path / "tampered.mco", flip_payload)
    with pytest.raises(mco.IntegrityError):
        mco.load(tampered)
    assert mco.inspect(tampered, verify=False).verified is False

    def future(name, body):
        if name != "mco.json":
            return body
        manifest = json.loads(body)
        manifest["container_version"] = 99
        return json.dumps(manifest).encode()
    with pytest.raises(mco.ModelFormatError, match="version 99"):
        mco.inspect(_rewrite(model_path, tmp_path / "future.mco", future))


def test_native_format_is_recognised_but_unsupported(tmp_path: Path) -> None:
    native = tmp_path / "MARCO-2.mco"
    native.write_bytes(NATIVE_MAGIC + b"\x00" * 64)
    info = mco.inspect(native)
    assert info.format == "mco-native" and not info.runnable and info.notes
    with pytest.raises(mco.UnsupportedFormatError):
        mco.load(native)


# --- running --------------------------------------------------------------------------

def test_multi_turn_run(model: mco.Model) -> None:
    model.reset()
    first = model.run("12만원 나왔어")
    assert first.status is mco.Status.NEEDS_INPUT
    assert first.evidence.of_kind("graph_path"), first.evidence
    final = model.run("3명이야")
    assert final.status is mco.Status.ANSWERED and "40000" in final.answer
    assert final.backend == "marco-kgpack" and final.input == "3명이야"
    assert final.trace.stage("route").detail["selected"].endswith("graph_정산_나눠내기.kg")
    assert final.raw is not None and "raw" not in final.to_dict()
    json.dumps(final.to_dict(include_raw=True), ensure_ascii=False)


def test_unknown_is_declined_offline(model: mco.Model) -> None:
    result = model.session().run("오늘 서울 날씨 어때")
    assert result.status is mco.Status.UNKNOWN and not result.ok and result.answer


def test_sessions_and_reset_are_isolated(model: mco.Model) -> None:
    a, b = model.session(), model.session()
    a.run("12만원 나왔어")
    assert "40000" not in b.run("3명이야").answer
    assert "40000" in a.run("3명이야").answer
    a.reset()
    assert "40000" not in a.run("3명이야").answer
    a.run("12만원 나왔어")
    a.close()
    with pytest.raises(mco.ModelClosedError):
        a.run("3명이야")
    # a closed session's runtime is reused, and must come back without its state
    with model.session() as c:
        assert "40000" not in c.run("3명이야").answer


def test_reason_is_self_contained(model: mco.Model) -> None:
    model.reset()
    model.run("12만원 나왔어")
    result = model.reason({"facts": ["돌은 23개 있다.", "돌 8개를 꺼냈다."], "question": "지금 돌은 몇 개야?"})
    assert result.status is mco.Status.ANSWERED and result.answer == "15개입니다."
    assert [s.stage for s in result.trace][:2] == ["fact", "fact"]
    assert result.evidence.of_kind("state_transition") and result.evidence.of_kind("fact")
    assert str(result.evidence.of_kind("derived_fact")[0]).startswith("[derived_fact] 돌.count = 15")
    assert len({json.dumps(e.to_dict(), sort_keys=True, ensure_ascii=False) for e in result.evidence}) \
        == len(result.evidence)
    # the default conversation was neither read nor changed
    assert "40000" in model.run("3명이야").answer
    # and nothing from the default conversation leaked into a later reason() call
    again = model.reason(mco.ReasoningInput(facts=("돌은 23개 있다.",), question="지금 돌은 몇 개야?"))
    assert again.answer == "23개입니다."


def test_reason_rejects_unsupported_input(model: mco.Model) -> None:
    with pytest.raises(mco.UnsupportedInputError):
        model.reason({"facts": [{"subject": "돌", "predicate": "count", "value": 23}], "question": "q?"})
    with pytest.raises(mco.InvalidInputError):
        model.reason("돌은 23개 있다.")  # type: ignore[arg-type]
    with pytest.raises(mco.InvalidInputError):
        model.run("   ")
    with pytest.raises(mco.InvalidInputError):
        model.run(3)  # type: ignore[arg-type]


def test_load_options_and_lifecycle(model_path: Path, tmp_path: Path) -> None:
    with pytest.raises(mco.InvalidInputError):
        mco.load(model_path, temperature=0.1)
    with pytest.raises(mco.BackendUnavailableError):
        mco.load(model_path, marco_root=str(tmp_path))
    with pytest.raises(mco.BackendUnavailableError):
        mco.load(model_path, backend="no-such-backend")
    loaded = mco.load(model_path, overlay_dir=str(tmp_path / "overlay"))
    assert (tmp_path / "overlay").is_dir()
    loaded.close()
    loaded.close()  # idempotent
    with pytest.raises(mco.ModelClosedError):
        loaded.run("3명이야")
    with pytest.raises(mco.ModelClosedError):
        loaded.reason(["돌은 23개 있다."])


def test_translate_plan_payload() -> None:
    payload = {"phase": "plan", "understanding": {}, "plan": {
        "plan_id": "p1", "type": "work", "actions": [{"id": "a1", "label": "read file"}], "unsupported": []}}
    result = translate(payload, "read README", "marco-kgpack")
    assert result.status is mco.Status.PENDING_APPROVAL and result.answer == "read file"
    assert result.trace.stage("plan").detail["plan_id"] == "p1" and result.raw_status == "plan"


@pytest.mark.parametrize("verdict,outcome,status", [
    ("인정", "성립", "answered"), ("인정", None, "needs_input"), ("인정", "무너짐", "rejected"),
    ("상태기억", None, "observed"), ("B2", None, "rejected"), ("미지", None, "unknown"),
    ("새판정", None, "unknown"),
])
def test_translate_verdicts(verdict: str, outcome, status: str) -> None:
    payload = {"phase": "answer", "answer": {"answer": "x", "result": outcome, "trace": {"verdict": verdict}}}
    assert translate(payload, "q", "marco-kgpack").status == status


# --- backend replaceability ----------------------------------------------------------

class _EchoSession(BackendSession):
    def __init__(self) -> None:
        self.turns: list[str] = []

    def run(self, text: str) -> mco.Result:
        self.turns.append(text)
        return mco.Result(answer=" | ".join(self.turns), status="answered", input=text, backend="echo",
                          evidence=[mco.Evidence("fact", text)], trace=[mco.TraceStep("echo", text)])

    def reset(self) -> None:
        self.turns = []


class _EchoModel(BackendModel):
    def __init__(self, info: mco.ModelInfo) -> None:
        self.info = info

    def new_session(self) -> BackendSession:
        return _EchoSession()


class _EchoBackend(Backend):
    name = "echo"
    formats = ("mco-compat", "kgpack")

    def describe(self, file):
        return mco.ModelInfo(path=str(file.path), format=file.kind, format_version=file.version,
                             size_bytes=file.size_bytes, sha256=file.sha256, backend=self.name,
                             runnable=True, capabilities=(mco.Capability.TEXT_INPUT, mco.Capability.TEXT_FACTS))

    def open(self, file, options):
        return _EchoModel(self.describe(file))


def test_backend_can_be_swapped_without_changing_user_code(model_path: Path) -> None:
    register_backend(_EchoBackend)
    try:
        with pytest.raises(ValueError):
            register_backend(_EchoBackend)

        def user_code(**load_kwargs):  # identical for both backends
            with mco.load(model_path, **load_kwargs) as m:
                r = m.run("12만원 나왔어")
                s = m.reason({"facts": ["돌은 23개 있다."], "question": "지금 돌은 몇 개야?"})
                return r.backend, isinstance(r.status, mco.Status), s.status, s.trace[0].stage

        assert user_code() == ("marco-kgpack", True, mco.Status.ANSWERED, "fact")
        assert user_code(backend="echo") == ("echo", True, mco.Status.ANSWERED, "fact")
        assert "echo" in mco.available_backends()
    finally:
        registered_backends.pop("echo", None)


# --- benchmark ------------------------------------------------------------------------

def test_benchmark(model: mco.Model, tmp_path: Path) -> None:
    cases = [
        {"id": "split", "turns": ["12만원 나왔어", "3명이야"], "status": "answered"},
        {"id": "state", "facts": ["돌은 23개 있다."], "question": "지금 돌은 몇 개야?", "answers": ["23개입니다."]},
        {"id": "weather", "input": "오늘 서울 날씨 어때", "unknown": True},
        {"id": "wrong", "input": "3명이야", "answers": ["다른 답"]},
        {"id": "timed-only", "input": "3명이야"},
    ]
    report = mco.benchmark(model, cases)
    by_id = {c.id: c for c in report.cases}
    assert [by_id[i].passed for i in ("split", "state", "weather", "wrong", "timed-only")] == \
        [True, True, True, False, None]
    assert (report.passed, report.scored, report.total) == (3, 4, 5)
    assert report.latency_ms()["median"] is not None and "3/4" in report.summary()
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases), encoding="utf-8")
    assert len(mco.load_cases(path)) == 5
    for bad in ([{"id": "x"}], [{"input": "a"}, {"input": "b", "id": "case-1"}],
                [{"input": "a", "status": "great"}], [{"turns": "a"}]):
        with pytest.raises(mco.InvalidInputError):
            mco.load_cases(bad)


def test_benchmark_reads_repository_case_format() -> None:
    cases = mco.load_cases(ROOT / "data/benchmarks/reasoning_transfer_v1.json")
    assert cases and all(c.turns for c in cases)
    assert any(c.unknown for c in cases) and any(c.answers for c in cases)


# --- CLI ---------------------------------------------------------------------------------

def _cli(*argv: str) -> tuple[int, str]:
    from mco.cli import main
    out = io.StringIO()
    return main(list(argv), stdout=out), out.getvalue()


def test_cli_inspect_run_compile(model_path: Path, tmp_path: Path) -> None:
    code, out = _cli("inspect", str(model_path), "--json")
    assert code == 0 and json.loads(out)["format"] == "mco-compat"
    code, out = _cli("inspect", str(model_path))
    assert code == 0 and "marco-kgpack" in out
    code, out = _cli("run", str(model_path), "12만원 나왔어", "3명이야", "--json")
    results = json.loads(out)
    assert code == 0 and results[-1]["status"] == "answered" and "40000" in results[-1]["answer"]
    code, out = _cli("run", str(model_path), "3명이야", "-v")
    assert code == 0 and "status:" in out and "trace:" in out
    code, out = _cli("compile", str(ROOT), "-o", str(tmp_path / "cli.mco"), "--graph", GRAPHS[0], "--json")
    assert code == 0 and json.loads(out)["info"]["graphs"] == 1
    code, out = _cli("backends")
    assert code == 0 and "marco-kgpack" in out and "mco-native" in out


def test_cli_benchmark_and_errors(model_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [
        {"id": "ok", "turns": ["12만원 나왔어", "3명이야"], "status": "answered"},
        {"id": "bad", "input": "3명이야", "answers": ["아니"]}]}, ensure_ascii=False), encoding="utf-8")
    report = tmp_path / "report.json"
    code, out = _cli("benchmark", str(model_path), str(cases), "--output", str(report))
    assert code == 0 and "1/2 passed" in out and "FAIL bad" in out
    assert json.loads(report.read_text(encoding="utf-8"))["passed"] == 1
    code, _ = _cli("benchmark", str(model_path), str(cases), "--fail-under", "0.9")
    assert code == 3
    code, _ = _cli("inspect", str(tmp_path / "missing.mco"))
    assert code == 1 and "ModelNotFoundError" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exit_info:
        _cli("frobnicate")
    assert exit_info.value.code == 2


def test_console_entry_point_runs_as_module(model_path: Path) -> None:
    out = subprocess.run([sys.executable, "-m", "mco", "inspect", str(model_path), "--json"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out)["name"] == "MARCO-1"
