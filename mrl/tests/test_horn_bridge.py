"""The source Horn bridge executes the native packet in generated C."""
import json
from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import unittest

from mrl import horn_bridge, native_graph, oracle, toolchain


def query(operation, facts, rules, **options):
    return {"kind": "horn_query", "type": "horn_result", "operation": operation,
            "plan": {"facts": facts, "rules": rules}, "limit": options.get("limit", 2048),
            "proof_limit": options.get("proof_limit", 32),
            "search_limit": options.get("search_limit", options.get("limit", 2048) * 8),
            "target": options.get("target")}


def fact(ident, triple, evidence=None, **extra):
    return {"id": ident, "triple": triple, "polarity": extra.get("polarity", True),
            "modality": extra.get("modality", "asserted"),
            "evidence": {} if evidence is None else evidence}


def rule(ident, body, head, version=None):
    return {"id": ident, "body": body, "head": head, "version": version}


def native_case(node):
    result = {"operation": node["operation"], "facts": [
        {"id": row["id"], "triple": row["triple"], "evidence": row["evidence"],
         "polarity": row["polarity"], "modality": row["modality"]}
        for row in node["plan"]["facts"]], "rules": [
        {"id": row["id"], "body": [row["body"]], "head": row["head"], "version": row["version"]}
        for row in node["plan"]["rules"]], "options": {
            "limit": node["limit"], **({"proof_limit": node["proof_limit"], "search_limit": node["search_limit"]}
                                            if node["operation"] == "closure_with_provenance" else {})}}
    if node["target"] is not None:
        result["target"] = node["target"]
    return result


@unittest.skipUnless(toolchain.find_compiler()[0] is not None, "no C compiler")
class HornBridgeTests(unittest.TestCase):
    def run_native_c(self, nodes):
        source = horn_bridge.emit_support(nodes) + "\nint main(void) {"
        source += "".join("mrl_horn_print_result(mrl_horn_run(%d));" % index
                          for index in range(len(nodes))) + "return 0;}\n"
        with tempfile.TemporaryDirectory(prefix="mrl-horn-") as folder:
            root = Path(folder); c_file, executable = root / "horn.c", root / "horn.exe"
            c_file.write_text(source, encoding="utf-8")
            try:
                toolchain.build_c(c_file, executable)
            except subprocess.CalledProcessError as failure:
                self.fail(failure.stderr.decode("utf-8", "replace"))
            run = subprocess.run([str(executable)], capture_output=True, text=True,
                                 encoding="utf-8", timeout=15)
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        return [json.loads(line) for line in run.stdout.splitlines()]

    def test_native_c_matches_adapter_and_oracle_for_supports_denial_and_bindings(self):
        facts = [fact("seed", ["a", "p", "b"], {"source": "가🙂x", "start": 0, "end": 2, "text": "가🙂"}),
                 fact("second", ["a", "p", "b"]), fact("deny", ["c", "p", "d"], polarity=False),
                 fact("blocked", ["c", "p", "d"]), fact("future", ["e", "p", "f"], modality="planned")]
        rules = [rule("r1", ["?x", "p", "?y"], ["?x", "q", "?y"], 'v"1'),
                 rule("r2", ["?x", "q", "?y"], ["?x", "r", "?y"], 2)]
        nodes = [query("closure", facts, rules, target=["a", "r", "b"]),
                 query("closure_with_provenance", facts, rules)]
        expected = [native_graph.evaluate(native_case(node)) for node in nodes]
        self.assertEqual(self.run_native_c(nodes), expected)
        self.assertEqual(expected[1], oracle.evaluate(native_case(nodes[1])))

    def test_native_c_preserves_provenance_limit_state(self):
        node = query("closure_with_provenance", [fact("seed", ["a", "p", "b"])],
                     [rule("r", ["?x", "p", "?y"], ["?x", "q", "?y"])],
                     limit=64, proof_limit=1, search_limit=1)
        expected = native_graph.evaluate(native_case(node))
        self.assertEqual(self.run_native_c([node]), [expected])
        self.assertEqual(expected, oracle.evaluate(native_case(node)))

    def test_empty_and_denial_only_queries_keep_oracle_empty_dicts(self):
        nodes = [query("closure", [], []), query("closure_with_provenance", [], []),
                 query("closure", [fact("deny", ["a", "p", "b"], polarity=False)], [])]
        expected = [native_graph.evaluate(native_case(node)) for node in nodes]
        self.assertEqual(self.run_native_c(nodes), expected)
        self.assertEqual(expected[0], {"known": {}})
        self.assertEqual(expected[1]["facts"], expected[1]["proof_bundles"], {})

    def test_missing_target_and_native_failures_have_checked_source_reasons(self):
        missing = query("closure", [fact("seed", ["a", "p", "b"])], [],
                        target=["missing-first-symbol", "p", "z"])
        limited = query("closure", [fact("seed", ["a", "p", "b"])],
                        [rule("r", ["?x", "p", "?y"], ["?x", "q", "?y"])], limit=1)
        capacity = query("closure", [fact("f%d" % index, ["n%d" % index, "p", "v%d" % index])
                                     for index in range(64)],
                         [rule("r", ["?x", "p", "?y"], ["?x", "q", "?y"])])
        output = self.run_native_c([missing, limited, capacity])
        self.assertEqual(output[0], {"known": {"$tuple_map": [{"key": ["a", "p", "b"],
                          "value": {"fact": ["a", "p", "b"], "evidence": {}}}]},
                         "complete": False, "reason": "target_not_found", "fact_count": 1,
                         "proof_count": 0, "searches": 0})
        self.assertEqual(output[1:], [{"error": "graph_limit"}, {"error": "native_capacity"}])

    def test_admission_rejects_hostile_ir_values(self):
        good = query("closure", [fact("seed", ["a", "p", "b"])], [])
        bad = []
        for path, value in [(("operation",), []), (("plan", "facts", 0, "modality"), []),
                            (("plan", "facts", 0, "id"), "bad\0"),
                            (("plan", "facts", 0, "triple", 0), "\ud800"),
                            (("plan", "facts", 0, "evidence"), {"source": "\ud800", "start": 0, "end": 0, "text": ""})]:
            node = deepcopy(good); target = node
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value; bad.append(node)
        version = query("closure", [fact("seed", ["a", "p", "b"])],
                        [rule("r", ["?x", "p", "?y"], ["?x", "q", "?y"], 2**31)])
        for node in [*bad, version]:
            with self.subTest(node=node), self.assertRaises(ValueError):
                horn_bridge.validate_query(node)

    def test_c_json_escapes_nested_proof_ids_without_changing_structure(self):
        facts = [fact('support"\\\n', ['a"\\\n', 'p"\\', 'b\n'],
                      {"source": "x\ny", "start": 1, "end": 2, "text": "\n"})]
        rules = [rule('r1"\\\n', ['?x', 'p"\\', '?y'], ['?x', 'q"\\', '?y'], 'v"\\\n'),
                 rule('r2"\\\n', ['?x', 'q"\\', '?y'], ['?x', 'r"\\', '?y'], 2)]
        node = query("closure_with_provenance", facts, rules)
        expected = native_graph.evaluate(native_case(node))
        self.assertEqual(self.run_native_c([node]), [expected])
        self.assertEqual(expected, oracle.evaluate(native_case(node)))


if __name__ == "__main__":
    unittest.main()
