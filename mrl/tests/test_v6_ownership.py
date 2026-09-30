import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.c_backend import emit_c
from mrl.frontend import compile_source
from mrl.toolchain import build_c


SOURCE = '''
fn make() -> list<f32> { return [1.0] }
fn size(xs: list<f32>) -> si { return xs.len }
fn main() {
  xs = [0.0]
  for (i in 0..200) { xs := make() n = size([2.0]) }
  print(xs.len)
}
'''


class V6OwnershipTests(unittest.TestCase):
    def test_managed_list_temps_are_released(self):
        code = emit_c(compile_source(SOURCE))
        hook = '''static int mrl_blocks;
static void *mrl_malloc(size_t n){void*p=malloc(n);if(p)++mrl_blocks;return p;}
static void *mrl_calloc(size_t a,size_t b){void*p=calloc(a,b);if(p)++mrl_blocks;return p;}
static void *mrl_realloc(void*p,size_t n){if(!p){void*q=realloc(p,n);if(q)++mrl_blocks;return q;}return realloc(p,n);}
static void mrl_free(void*p){if(p)--mrl_blocks;free(p);}
#define malloc mrl_malloc
#define calloc mrl_calloc
#define realloc mrl_realloc
#define free mrl_free
'''
        code = code.replace("static void mrl_runtime_fail", hook + "static void mrl_runtime_fail", 1)
        at = code.rfind("    return 0;\n}")
        self.assertGreaterEqual(at, 0)
        code = code[:at] + code[at:].replace("    return 0;", "    return mrl_blocks ? 99 : 0;", 1)
        with tempfile.TemporaryDirectory(prefix="mrl-v6-own-") as directory:
            source, executable = Path(directory) / "source.c", Path(directory) / "source.exe"
            source.write_text(code, encoding="utf-8")
            build_c(source, executable)
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
        self.assertEqual((run.returncode, run.stdout.splitlines()), (0, ["1"]))


if __name__ == "__main__": unittest.main()
