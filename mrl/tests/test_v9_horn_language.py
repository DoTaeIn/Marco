import json
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from mrl.c_backend import emit_c
from mrl.frontend import MrlError, compile_source
from mrl.horn_bridge import validate_plan_constructor_v7
from mrl.toolchain import build_c


SOURCE = (Path(__file__).parents[1] / "examples" / "growing_knowledge.mrl").read_text(encoding="utf-8")


class V9HornLanguageTests(unittest.TestCase):
    def test_source_methods_chain_and_persistence(self):
        ir = compile_source(SOURCE)
        self.assertEqual(ir["version"], 7)
        with tempfile.TemporaryDirectory(prefix="mrl-v9-horn-") as directory:
            source, executable = Path(directory) / "source.c", Path(directory) / "source.exe"
            source.write_text(emit_c(ir), encoding="utf-8")
            build_c(source, executable)
            run = subprocess.run([str(executable)], cwd=directory, capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual((run.returncode, run.stdout.splitlines()), (0, ["2"]))

    def test_ir7_methods_are_independently_checked(self):
        ir = compile_source(SOURCE)
        bad = deepcopy(ir)
        def walk(value):
            if isinstance(value, dict):
                if value.get("kind") == "horn_count":
                    value["type"] = "b"
                    return True
                return any(walk(child) for child in value.values())
            return any(walk(child) for child in value) if isinstance(value, list) else False
        self.assertTrue(walk(bad))
        with self.assertRaises(ValueError): emit_c(bad)

    def test_v7_rejects_nonliteral_budget_and_unsafe_method_inputs(self):
        with self.assertRaises(MrlError):
            compile_source('fn main() -> si { n = 4 p: Horn = Horn(memory_budget=n, facts=Facts(), rules=Rules()) return 0 }')
        with self.assertRaises(MrlError):
            compile_source('fn main() -> si { p: Horn = Horn(memory_budget=4, facts=Facts(), rules=Rules()) p.count("wrong") return 0 }')

    def test_v7_selective_queries_large_capacity_and_unicode_evidence(self):
        source = '''
fn main() -> si {
  p: Horn = Horn(memory_budget = 67108864, capacity = 30000,
    facts = Facts(Fact(id = "한", subject = "a", predicate = "p", object = "b", evidence = Evidence(source = "가🙂", start = 0, end = 2, text = "가🙂"))),
    rules = Rules())
  loaded = p.load("facts.jsonl")
  match (loaded) { Ok(rows) {
    all = p.count()
    filtered = p.count(predicate = "p")
    selected = p.select(predicate = "p")
    unicode = p.select(subject = "a")
    print(unicode)
    return all + filtered + selected.fact_count
  } Err(error) { return 0 } }
}'''
        ir = compile_source(source)
        self.assertEqual(ir["version"], 7)
        with tempfile.TemporaryDirectory(prefix="mrl-v9-filter-") as directory:
            c_file, executable = Path(directory) / "source.c", Path(directory) / "source.exe"
            c_file.write_text(emit_c(ir), encoding="utf-8")
            facts = Path(directory) / "facts.jsonl"
            facts.write_text("\n".join(json.dumps({"id": "row%d" % index, "subject": "s%d" % index,
                "predicate": "p", "object": "o%d" % index,
                "evidence": {"source": "가🙂", "start": 0, "end": 2, "text": "가🙂"}}, ensure_ascii=False)
                for index in range(19999)), encoding="utf-8")
            build_c(c_file, executable)
            run = subprocess.run([str(executable)], cwd=directory, capture_output=True, text=True, encoding="utf-8", timeout=10)
        lines = run.stdout.splitlines()
        self.assertEqual((run.returncode, lines[-1:]), (0, ["60000"]))
        evidence = json.loads(lines[0])["known"]["$tuple_map"][0]["value"]["evidence"]
        self.assertEqual(evidence, {"source": "가🙂", "start": 0, "end": 2, "text": "가🙂"})

    def test_v7_rejects_hostile_rules_and_raw_mutations(self):
        base = {"facts": [], "rules": [], "capacity": 20000, "memory_budget": 1}
        hostile = (
            {**base, "facts": None},
            {**base, "rules": None},
            {**base, "rules": [{"id": "r", "body": [1], "head": None, "version": None}]},
            {**base, "rules": [{"id": "r", "body": [["?", "p", "x"]], "head": ["?", "q", "x"], "version": None}]},
            {**base, "rules": [{"id": "r", "body": [["a", "p", "b"]], "head": ["a", "q", "b"], "version": True}]},
            {**base, "rules": [{"id": "r", "body": [["a", "p", "b"]], "head": ["a", "q", "b"], "version": 2 ** 31}]},
        )
        for plan in hostile:
            with self.subTest(plan=plan), self.assertRaises(ValueError): validate_plan_constructor_v7(plan)
        ir = compile_source(SOURCE)
        def walk(value):
            if isinstance(value, dict):
                yield value
                for child in value.values(): yield from walk(child)
            elif isinstance(value, list):
                for child in value: yield from walk(child)
        for node in walk(ir):
            if node.get("kind") == "horn_count": node["triple"] = ["a\0", None, None]
        with self.assertRaises(ValueError): emit_c(ir)

    def test_raw_restore_and_commit_require_a_mutable_plan(self):
        for method in ("restore", "commit"):
            source = '''
fn main() -> si {
  p: Horn = Horn(memory_budget = 4, facts = Facts(), rules = Rules())
  result = p.%s("checkpoint")
  return 0
}''' % method
            ir = compile_source(source)
            for statement in ir["functions"][0]["body"]:
                if statement.get("kind") == "let" and statement.get("name") == "p": statement["mutable"] = False
            with self.subTest(method=method), self.assertRaises(ValueError): emit_c(ir)

    def test_ir7_rejects_static_closure_and_mixed_legacy_constructor(self):
        static = '''
fn main() -> si {
  p: Horn = Horn(memory_budget = 4, facts = Facts(), rules = Rules())
  old = closure(Horn(facts = Facts(), rules = Rules()))
  return 0
}'''
        with self.assertRaisesRegex(MrlError, "static Horn closure is unavailable"):
            compile_source(static)
        legacy = compile_source('fn main() -> si { old = closure(Horn(facts = Facts(), rules = Rules())) return 0 }')
        legacy["version"] = 7
        with self.assertRaisesRegex(ValueError, "static Horn closure is unavailable"):
            emit_c(legacy)
        mixed = '''
fn main() -> si {
  old: Horn = Horn(facts = Facts(), rules = Rules())
  p: Horn = Horn(memory_budget = 4, facts = Facts(), rules = Rules())
  return 0
}'''
        with self.assertRaisesRegex(MrlError, "memory_budget"):
            compile_source(mixed)


if __name__ == "__main__": unittest.main()
