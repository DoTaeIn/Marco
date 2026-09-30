import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.__main__ import main
from mrl.toolchain import build_c, find_compiler


ROOT = Path(__file__).parents[1]


@unittest.skipUnless(find_compiler()[0] is not None, "no complete C11 toolchain")
class ValueRuntimeTests(unittest.TestCase):
    def run_source(self, source):
        with tempfile.TemporaryDirectory() as folder:
            mrl = Path(folder) / "value.mrl"; c = mrl.with_suffix(".c"); exe = mrl.with_suffix(".exe")
            mrl.write_text(source, encoding="utf-8")
            self.assertEqual(main([str(mrl), "-o", str(c)]), 0)
            build_c(c, exe, optimization="debug")
            return subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)

    def test_source_arrays_lists_and_f32_kernels(self):
        source = (ROOT / "examples" / "numeric_values.mrl").read_text(encoding="utf-8")
        result = self.run_source(source)
        self.assertEqual((result.returncode, result.stderr, result.stdout.splitlines()), (0, "", ["3", "8", "3", "36.9599991", "7"]))

    def run_c(self, body):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "value.c"; executable = source.with_suffix(".exe")
            runtime = (ROOT / "runtime" / "value_runtime.h").read_text(encoding="utf-8")
            source.write_text("""#include <stdio.h>
#include <stdlib.h>
static void mrl_runtime_fail(const char *message) { fputs(message, stderr); exit(72); }
""" + runtime + "\n" + body, encoding="utf-8")
            build_c(source, executable, optimization="debug")
            return subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)

    def test_list_aliasing_bounds_and_f32_kernels(self):
        result = self.run_c("""
int main(void) {
  float three = 3.0f, four = 4.0f, zero = 0.0f;
  MrlList *left = mrl_list_new_f32(0), *alias = mrl_list_copy(left);
  mrl_list_push(left, &three); mrl_list_push(alias, &four); mrl_list_push(left, &zero);
  MrlList *right = mrl_list_new_f32(0); mrl_list_push(right, &four); mrl_list_push(right, &three); mrl_list_push(right, &zero);
  if (mrl_list_len(left) != 3 || *(float *)mrl_list_at(alias, 1) != 4.0f) return 1;
  if (fabsf(mrl_f32_sum(left) - 7.0f) > 0.00001f) return 2;
  if (fabsf(mrl_f32_dot(left, right) - 24.0f) > 0.00001f) return 3;
  if (fabsf(mrl_f32_norm(left) - 5.0f) > 0.00001f) return 4;
  if (fabsf(mrl_f32_cosine(left, right) - 0.96f) > 0.00001f) return 5;
  mrl_list_release(alias); mrl_list_release(left); mrl_list_release(right); return 0;
}
""")
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_checked_failure_paths(self):
        cases = {
            "index": "MrlList *x=mrl_list_new_f32(0); mrl_list_at(x,0);",
            "length": "float x=1; MrlList *a=mrl_list_new_f32(0),*b=mrl_list_new_f32(0); mrl_list_push(a,&x); mrl_f32_dot(a,b);",
            "zero": "float x=0; MrlList *a=mrl_list_new_f32(0); mrl_list_push(a,&x); mrl_f32_cosine(a,a);",
            "nonfinite": "float x=NAN; MrlList *a=mrl_list_new_f32(0); mrl_list_push(a,&x); mrl_f32_sum(a);",
            "wrong_type": "int32_t x=1; MrlList *a=mrl_list_new(sizeof x,0); mrl_list_push(a,&x); mrl_f32_sum(a);",
            "overflow": "float x=FLT_MAX; MrlList *a=mrl_list_new_f32(0); mrl_list_push(a,&x); mrl_list_push(a,&x); mrl_f32_sum(a);",
        }
        for name, body in cases.items():
            with self.subTest(name=name):
                result = self.run_c("int main(void) { " + body + " return 0; }")
                self.assertEqual(result.returncode, 72)
                self.assertIn("MRL", result.stderr)

    def test_push_from_self_survives_growth_and_repeated_references(self):
        result = self.run_c("""
int main(void) {
  float x = 2.0f; MrlList *a = mrl_list_new_f32(1); mrl_list_push(a, &x);
  mrl_list_push(a, mrl_list_at(a, 0));
  if (mrl_list_len(a) != 2 || *(float *)mrl_list_at(a, 1) != 2.0f) return 1;
  for (int i = 0; i < 100; ++i) mrl_list_retain(a);
  for (int i = 0; i < 100; ++i) mrl_list_release(a);
  if (*(float *)mrl_list_at(a, 0) != 2.0f) return 2;
  mrl_list_release(a); return 0;
}
""")
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_strict_jsonl_parser(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); c = root / "json.c"; exe = c.with_suffix(".exe")
            header = (ROOT / "runtime" / "horn_jsonl.h").read_text(encoding="utf-8")
            c.write_text("""#include <stdio.h>
""" + header + '''
int main(void) { FILE *f=fopen("facts.jsonl","wb"); fputs("{\\"id\\":\\"a\\",\\"subject\\":\\"u\\",\\"predicate\\":\\"p\\",\\"object\\":\\"v\\",\\"evidence\\":{\\"source\\":\\"가🙂b\\",\\"start\\":0,\\"end\\":2,\\"text\\":\\"가🙂\\"}}\\n",f); fclose(f); MrlHornJsonBatch b=mrl_horn_jsonl_load("facts.jsonl",4096,4); if(b.error||b.count!=1||strcmp(b.facts[0].object,"v"))return 1; mrl_horn_jsonl_free(&b); f=fopen("bad.jsonl","wb"); fputs("{\\"id\\":\\"a\\",\\"subject\\":\\"u\\",\\"predicate\\":\\"p\\",\\"object\\":\\"v\\",\\"evidence\\":{\\"source\\":\\"가🙂b\\",\\"start\\":0,\\"end\\":2,\\"text\\":\\"é\\"}}\\n",f); fclose(f); b=mrl_horn_jsonl_load("bad.jsonl",4096,4); if(!b.error||b.count)return 2; return 0; }''', encoding="utf-8")
            build_c(c, exe, optimization="debug")
            result = subprocess.run([str(exe)], cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_jsonl_trust_boundary_matrix(self):
        valid = b'{"id":"a","triple":["u","p","v"],"polarity": true,"evidence":{}}\n'
        unicode = '{"id":"u","subject":"x","predicate":"p","object":"y","polarity": false,"evidence":{"source":"가🙂b","start":0,"end":2,"text":"가🙂"}}'.encode()
        cases = {
            "valid": (valid, True, 4096), "unicode": (unicode, True, 4096),
            "nul": (b'{"id":"\\u0000","triple":["u","p","v"]}', False, 4096),
            "utf8": (b'{"id":"a","triple":["u","p","\xc3"]}', False, 4096),
            "surrogate": (b'{"id":"a","triple":["\\ud800","p","v"]}', False, 4096),
            "span": ('{"id":"a","triple":["u","p","v"],"evidence":{"source":"가🙂b","start":0,"end":2,"text":"é"}}'.encode(), False, 4096),
            "plus": (b'{"id":"a","triple":["u","p","v"],"evidence":{"source":"x","start":+1,"end":1,"text":""}}', False, 4096),
            "leading": (b'{"id":"a","triple":["u","p","v"],"evidence":{"source":"x","start":00,"end":0,"text":""}}', False, 4096),
            "overflow": (b'{"id":"a","triple":["u","p","v"],"evidence":{"source":"x","start":2147483648,"end":1,"text":"x"}}', False, 4096),
            "duplicate_id": (valid + b'{"id":"a","triple":["u","p","w"]}', False, 4096),
            "unknown": (b'{"id":"a","triple":["u","p","v"],"nope":1}', False, 4096),
            "duplicate_key": (b'{"id":"a","id":"b","triple":["u","p","v"]}', False, 4096),
            "mixed_named_first": (b'{"id":"a","subject":"u","triple":["u","p","v"]}', False, 4096),
            "mixed_triple_first": (b'{"id":"a","triple":["u","p","v"],"subject":"u"}', False, 4096),
            "bytecap": (valid, False, 4),
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); c = root / "loader.c"; exe = c.with_suffix(".exe")
            header = (ROOT / "runtime" / "horn_jsonl.h").read_text(encoding="utf-8")
            c.write_text("#include <stdio.h>\n" + header + '\nint main(int n,char**v){MrlHornJsonBatch b=mrl_horn_jsonl_load(v[1],(size_t)strtoul(v[2],0,10),8); printf("%d\\n",b.error?0:b.count);mrl_horn_jsonl_free(&b);return 0;}', encoding="utf-8")
            build_c(c, exe, optimization="debug")
            for name, (data, accepted, limit) in cases.items():
                path = root / (name + ".jsonl"); path.write_bytes(data)
                result = subprocess.run([str(exe), str(path), str(limit)], capture_output=True, text=True, timeout=10)
                with self.subTest(name=name): self.assertEqual((result.returncode == 0 and result.stdout.strip() != "0"), accepted)

    def test_jsonl_utf8_windows_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); name = "지식🙂.jsonl"; (root / name).write_bytes(b'{"id":"a","triple":["u","p","v"]}\n')
            c = root / "unicode.c"; exe = c.with_suffix(".exe"); header = (ROOT / "runtime" / "horn_jsonl.h").read_text(encoding="utf-8")
            c.write_text('#include <stdio.h>\n' + header + '\nint main(void){MrlHornJsonBatch b=mrl_horn_jsonl_load("지식🙂.jsonl",4096,8);int ok=!b.error&&b.count==1;mrl_horn_jsonl_free(&b);return ok?0:1;}', encoding="utf-8")
            build_c(c, exe, optimization="debug")
            result = subprocess.run([str(exe)], cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual((result.returncode, result.stderr), (0, ""))


if __name__ == "__main__":
    unittest.main()
