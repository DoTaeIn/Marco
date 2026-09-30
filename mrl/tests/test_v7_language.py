import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.c_backend import emit_c
from mrl.frontend import compile_source
from mrl.toolchain import build_c


class V7LanguageTests(unittest.TestCase):
    def test_mutable_array_write_is_checked(self):
        source = 'fn main() -> si { a: arr<si,2> = [1,2] a[1] := 7 return a[1] }'
        with tempfile.TemporaryDirectory(prefix="mrl-arr-") as directory:
            c, exe = Path(directory) / "a.c", Path(directory) / "a.exe"; c.write_text(emit_c(compile_source(source))); build_c(c, exe)
            self.assertEqual(subprocess.run([str(exe)], capture_output=True, text=True).stdout.splitlines(), ["7"])
    def test_map_set_get_replace_remove_len_alias_return(self):
        source = '''
fn pass(m: map<s,si>) -> map<s,si> { return m }
fn main() -> si {
  dec m: map<s,si> = Map()
  alias = m
  alias.set("a", 1)
  alias.set("a", 2)
  returned = pass(alias)
  print(returned.len)
  match (returned.get("a")) { Ok(x) { print(x) } Err(e) { return 9 } }
  returned.remove("a")
  print(m.len)
  match (m.get("a")) { Ok(x) { return 8 } Err(e) { return 1 } }
}
'''
        with tempfile.TemporaryDirectory(prefix="mrl-v7-map-") as directory:
            c, exe = Path(directory) / "map.c", Path(directory) / "map.exe"
            c.write_text(emit_c(compile_source(source)), encoding="utf-8")
            build_c(c, exe)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["1", "2", "0", "1"]))


if __name__ == "__main__": unittest.main()
