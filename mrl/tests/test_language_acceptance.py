"""Independent acceptance boundaries for the language completion delivery."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from mrl.frontend import compile_source
from mrl.c_backend import emit_c
from mrl.toolchain import build_c


def native(source, track=False):
    code = emit_c(compile_source(source))
    if track:
        hook = """static int accepted_blocks;
static void *accepted_malloc(size_t n){void*p=malloc(n);if(p)++accepted_blocks;return p;}
static void *accepted_calloc(size_t a,size_t b){void*p=calloc(a,b);if(p)++accepted_blocks;return p;}
static void *accepted_realloc(void*p,size_t n){void*q=realloc(p,n);if(!p&&q)++accepted_blocks;return q;}
static void accepted_free(void*p){if(p)--accepted_blocks;free(p);}
#define malloc accepted_malloc
#define calloc accepted_calloc
#define realloc accepted_realloc
#define free accepted_free
"""
        if track == "poison":
            # Quarantine logically freed blocks so a stale managed reference fails
            # deterministically instead of depending on Windows heap reuse timing.
            hook = """static int accepted_blocks;
static struct {void *p; size_t n; int live;} accepted_items[4096];
static size_t accepted_count;
static void accepted_record(void*p,size_t n){if(p){if(accepted_count==4096)abort();accepted_items[accepted_count].p=p;accepted_items[accepted_count].n=n;accepted_items[accepted_count++].live=1;++accepted_blocks;}}
static void *accepted_malloc(size_t n){void*p=malloc(n);accepted_record(p,n);return p;}
static void *accepted_calloc(size_t a,size_t b){void*p=calloc(a,b);accepted_record(p,a*b);return p;}
static void *accepted_realloc(void*p,size_t n){
 size_t i=0;while(i<accepted_count&&accepted_items[i].p!=p)++i;
 if(p&&(i==accepted_count||!accepted_items[i].live))abort();
 void*q=realloc(p,n);if(!q)return q;
 if(!p)accepted_record(q,n);else{accepted_items[i].p=q;accepted_items[i].n=n;}return q;
}
static void accepted_free(void*p){
 if(!p)return;size_t i=0;while(i<accepted_count&&accepted_items[i].p!=p)++i;
 if(i==accepted_count||!accepted_items[i].live)abort();
 accepted_items[i].live=0;--accepted_blocks;memset(p,255,accepted_items[i].n);
}
static int accepted_status(void){int result=accepted_blocks?99:0;for(size_t i=0;i<accepted_count;i++)free(accepted_items[i].p);return result;}
#define malloc accepted_malloc
#define calloc accepted_calloc
#define realloc accepted_realloc
#define free accepted_free
"""
        code = code.replace("static void mrl_runtime_fail", hook + "static void mrl_runtime_fail", 1)
        at = code.rfind("    return 0;\n}")
        if at < 0: raise AssertionError("native main return marker changed")
        code = code[:at] + code[at:].replace("    return 0;", "    return accepted_status();" if track == "poison" else "    return accepted_blocks ? 99 : 0;", 1)
    with tempfile.TemporaryDirectory(prefix="mrl-acceptance-") as directory:
        c, executable = Path(directory)/"app.c", Path(directory)/"app.exe"
        c.write_text(code, encoding="utf-8")
        try:
            build_c(c, executable)
        except subprocess.CalledProcessError as error:
            raise AssertionError(error.stderr.decode("utf-8", "replace") if isinstance(error.stderr, bytes) else error.stderr) from error
        return subprocess.run([str(executable)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)


class LanguageAcceptanceTests(unittest.TestCase):
    def test_observable_short_circuit_and_evaluation_order(self):
        result = native("""
fn tick(n: si) -> b { print(n) return true }
fn main() {
 if (false and tick(9)) { print(90) }
 if (true or tick(8)) { print(1) }
 if (tick(2) and tick(3)) { print(4) }
 if (not false) { print(5) }
}
""")
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["1", "2", "3", "4", "5"]))

    def test_short_circuit_managed_rhs_stays_within_its_branch(self):
        result = native("""
fn values() -> list<si> { print(7) return [1,2] }
fn main() {
 if (false and values().len > 0) { print(90) }
 if (true or values().len > 0) { print(1) }
 if (true and values().len > 0) { print(2) }
 if (false or values().len > 0) { print(3) }
}
""", track=True)
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["1", "7", "2", "7", "3"]))

    def test_fixed_width_arithmetic_against_integer_oracle(self):
        statements, expected = [], []
        for signed in (True, False):
            for width in (8, 16, 32, 64):
                typ = ("si" if signed else "ui") + str(width)
                low, high = (-(2 ** (width-1)), 2 ** (width-1)-1) if signed else (0, 2**width-1)
                values = [low, low+1, -17, -1, 0, 1, 17, high-1, high] if signed else [0, 1, 17, high-1, high]
                for a, b in zip(values, reversed(values)):
                    for op in ("+", "-", "*", "/", "%"):
                        if op in ("/", "%") and b == 0: continue
                        quotient = (abs(a)//abs(b)) * (-1 if (a<0) != (b<0) else 1) if b else 0
                        value = {"+": a+b, "-": a-b, "*": a*b, "/": quotient, "%": a-quotient*b}[op]
                        if not low <= value <= high: continue
                        index = len(expected)
                        statements.append(f"a{index}: {typ} = {a} b{index}: {typ} = {b} print(a{index} {op} b{index})")
                        expected.append(str(value))
        result = native("fn main() { " + " ".join(statements) + " }")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), expected)

    def test_signed_division_and_remainder_edges(self):
        result = native("""fn main() { print(-17 / 3) print(-17 % 3) print(17 / -3) print(17 % -3) print(-2147483648 % -1) }""")
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["-5", "-2", "-5", "2", "0"]))
        overflow = native("fn main() -> si { return -2147483648 / -1 }")
        self.assertNotEqual(overflow.returncode, 0)
        self.assertIn("overflow", overflow.stderr)

    def test_forged_jump_outside_loop_is_rejected(self):
        for kind in ("break", "continue"):
            ir = compile_source("fn main() { values = [1] print(values.len) }")
            ir["functions"][0]["body"].append({"kind": kind})
            with self.subTest(kind=kind), self.assertRaises(ValueError): emit_c(ir)

    def test_checked_cast_widens_signed_values_without_truncated_bounds(self):
        result = native("fn main() { x: si8 = 42 y: si8 = -42 print(si64(x)) print(si32(y)) }")
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["42", "-42"]))

    def test_float_cast_rejects_exclusive_integer_upper_bound(self):
        for typ, boundary in (("si64", "9223372036854775808.0"), ("ui64", "18446744073709551616.0")):
            with self.subTest(type=typ):
                result = native(f"fn main() {{ x: f64 = {boundary} print({typ}(x)) }}")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("checked cast", result.stderr)

    def test_nested_conditional_loop_exit_releases_managed_values(self):
        result = native("""
fn main() {
 outside = [1]
 for (i in 0..4) {
  keep = [i]
  while (true) {
   inner = [2,3]
   if (i == 1) { nested = [4] break }
   break
  }
  if (i == 0) { skipped = [5] continue }
  print(keep.len)
 }
 print(outside.len)
}
""", track=True)
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["1", "1", "1", "1"]))


class TypeAcceptanceTests(unittest.TestCase):
    def test_optional_managed_payload_survives_nested_match_and_return(self):
        result = native("""
struct Box { values: list<si> }
fn make() -> Box? { return Some(Box(values=[7,8])) }
fn take(value: Box?) -> list<si> {
 match(value) { Some(box) { return box.values } none { return [0] } }
}
fn main() {
 value: Box? = make()
 values = take(value)
 print(values[0])
 empty: Box? = none
 print(take(empty)[0])
}
""", track=True)
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["7", "0"]))

    def test_condition_and_match_temporaries_have_lexical_lifetimes(self):
        programs = (
            ("fn values()->list<si>{return [1]} fn main(){if(values().len == 0){print(9)} else {print(1)}}", ["1"]),
            ("fn values()->list<si>{return [1]} fn main(){while(values().len == 0){print(9)} print(1)}", ["1"]),
            ("struct Box{values:list<si>} fn make()->Box?{return Some(Box(values=[7,8]))} fn main(){match(make()){Some(box){print(box.values[0]) print(box.values[1])} none{print(0)}}}", ["7", "8"]),
        )
        for source, expected in programs:
            with self.subTest(source=source):
                result = native(source, track="poison")
                self.assertEqual((result.returncode, result.stdout.splitlines()), (0, expected), result.stderr)

    def test_graph_retains_managed_payloads_and_releases_removed_slots(self):
        result = native("""
struct Place { name: s position: si }
struct Road { distance: si label: s }
relation Travel { Link { polarity: positive evidence: optional traverse: forward } }
graph roads { node: Place relation: Travel edge: Road }
fn estimate(node: Place, goal: Place) -> si { return goal.name.len - 4 }
fn main() {
 temporary = roads.add(Place(name="old" + " value",position=0))
 roads.remove(temporary)
 start = roads.add(Place(name="sta" + "rt",position=0))
 goal = roads.add(Place(name="go" + "al",position=1))
 roads.add(start,goal,Travel.Link,Road(distance=7,label="ro" + "ad"))
 found = roads.find(start,goal) { method: astar cost: edge.distance heuristic: estimate(node,goal) }
 match(found) { Ok(path) { print(path.cost) } Err(error) { print(error) } }
 roads.remove(start)
}
""", track="poison")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "7")

    def test_foreach_owns_fresh_iterables_and_current_managed_item(self):
        result = native("""
fn words()->list<s> { return ["a", "bb", "ccc"] }
fn main() {
 for (word in words()) { if(word.len == 1) { continue } print(word) if(word.len == 2) { break } }
 values: map<s,si> = Map()
 values.set("key", 1)
 alias = values
 for (key in values) { alias.remove(key) print(key) }
}
""", track="poison")
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["bb", "key"]), result.stderr)

    def test_match_payload_survives_reassignment_of_its_parent(self):
        result = native("""
fn main() {
 value: s? = Some("old")
 match(value) { Some(text) { value := none print(text) } none {} }
 result: Result<s,s> = Ok("yes")
 match(result) { Ok(text) { result := Err("changed") print(text) } Err(error) { print(error) } }
}
""", track="poison")
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["old", "yes"]), result.stderr)

    def test_raw_enum_and_optional_ir_cannot_bypass_type_checks(self):
        from copy import deepcopy
        enum = compile_source("enum E { A B } fn main()->si { match(E.A) { A { return 1 } B { return 2 } } }")
        for mutation in ("missing", "duplicate", "value"):
            bad = deepcopy(enum)
            match = bad["functions"][0]["body"][0]
            if mutation == "missing": match["arms"].pop()
            elif mutation == "duplicate": match["arms"][1]["member"] = "A"
            else: match["value"]["member"] = "Missing"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): emit_c(bad)
        option = compile_source("fn main(){ value: si? = Some(3) }")
        for mutation in ("tag", "payload", "none_payload"):
            bad = deepcopy(option)
            value = bad["functions"][0]["body"][0]["value"]
            if mutation == "tag": value["some"] = 1
            elif mutation == "payload": value["value"] = {"kind":"literal", "type":"s", "value":"wrong"}
            else: value["some"] = False
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): emit_c(bad)


class ModuleAcceptanceTests(unittest.TestCase):
    def modules(self, files):
        from mrl.__main__ import _load_source
        with tempfile.TemporaryDirectory(prefix="mrl-module-acceptance-") as directory:
            root = Path(directory)
            for name, source in files.items(): (root/name).write_text(source, encoding="utf-8")
            return native(_load_source(root/"main.mrl"))

    def test_module_local_and_field_names_do_not_become_globals(self):
        result = self.modules({
            "lib.mrl": "struct Row { value: si } fn value() -> si { return 1 } fn local() -> si { value = 9 return value }",
            "main.mrl": 'import "lib.mrl" as lib\nfn main() -> si { r = lib.Row(value=3) return lib.local() + r.value }',
        })
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["12"]))

    def test_module_typed_locals_and_match_binders_preserve_scopes(self):
        result = self.modules({
            "lib.mrl": "fn value()->si{return 7} fn local()->si { if(true){value: si = 9 print(value)} print(value()) option: si? = Some(4) match(option){Some(value){return value} none{return 0}} }",
            "main.mrl": 'import "lib.mrl" as lib\nfn main()->si{return lib.local()}',
        })
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["9", "7", "4"]), result.stderr)

    def test_module_extern_names_preserve_native_symbol(self):
        result = self.modules({
            "lib.mrl": 'extern fn c_abs(value:si)->si="abs" fn absolute(value:si)->si{unsafe{return c_abs(value)}}',
            "main.mrl": 'import "lib.mrl" as lib\nfn main()->si{return lib.absolute(-8)}',
        })
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["8"]), result.stderr)

    def test_nested_modules_keep_aliases_local(self):
        result = self.modules({
            "one.mrl": "fn get() -> si { return 3 }",
            "two.mrl": "fn get() -> si { return 7 }",
            "left.mrl": 'import "one.mrl" as x\nfn get() -> si { return x.get() }',
            "right.mrl": 'import "two.mrl" as x\nfn get() -> si { return x.get() }',
            "main.mrl": 'import "left.mrl" as left\nimport "right.mrl" as right\nfn main() -> si { return left.get() + right.get() }',
        })
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["10"]))

    def test_namespaced_diagnostic_keeps_original_column(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from mrl.__main__ import main
        line = "fn broken() -> si { return missing }"
        with tempfile.TemporaryDirectory(prefix="mrl-module-location-") as directory:
            root = Path(directory)
            library, entry = root/"library.mrl", root/"main.mrl"
            library.write_text(line, encoding="utf-8")
            entry.write_text('import "library.mrl" as unusually_long_alias\nfn main() -> si { return unusually_long_alias.broken() }', encoding="utf-8")
            output = StringIO()
            with redirect_stderr(output): result = main(["check", str(entry)])
            self.assertEqual(result, 1)
            self.assertIn(f"{library.resolve()}:1:{line.index('missing')+1}:", output.getvalue())

    def test_paired_comment_does_not_import_or_hide_following_function(self):
        result = self.modules({
            "lib.mrl": '#\nimport "does-not-exist.mrl"\n# fn get() -> si { return 5 }',
            "main.mrl": 'import "lib.mrl" as lib\nfn main() -> si { return lib.get() }',
        })
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["5"]))


if __name__ == "__main__": unittest.main()
