import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.toolchain import build_c, find_compiler

ROOT = Path(__file__).parents[1]


@unittest.skipUnless(find_compiler()[0], "no C11 compiler")
class LanguageIoTests(unittest.TestCase):
    def test_native_utf8_io_argv_bounds_and_atomic_failure(self):
        with tempfile.TemporaryDirectory(prefix="mrl-io-") as directory:
            root = Path(directory)
            input_path = root / "입력 파일.txt"
            output_path = root / "출력 파일.txt"
            invalid_path = root / "invalid.bin"
            nul_path = root / "nul.bin"
            input_path.write_bytes("안녕\nMRL".encode("utf-8"))
            output_path.write_text("기존", encoding="utf-8")
            invalid_path.write_bytes(b"bad\xff")
            nul_path.write_bytes(b"ok\0bad")
            header = (ROOT / "runtime" / "language_io.h").read_text(encoding="utf-8")
            source = header + """
#include <stdio.h>
static int same(const char *a, const char *b) { return a && b && strcmp(a, b) == 0; }
static int same_arg(int index, const char *expected) {
    MrlIoStringResult value = mrl_io_argv(index);
    int matched = value.ok && same(value.value, expected);
    mrl_io_string_release(value.value);
    return matched;
}
int main(int argc, char **argv) {
    const char *error = NULL;
    MrlIoStringResult value, missing, invalid, nul, argument;
    mrl_io_set_argv(argc, argv);
    if (mrl_io_argc() != argc || argc != 6) return 1;
    argument = mrl_io_argv(1);
    if (!argument.ok || !same(argument.value, "인자🙂")) return 2;
    mrl_io_string_release(argument.value);
    if (!same_arg(2, "") || !same_arg(3, "a\\\"b") || !same_arg(4, "C:\\\\path with space\\\\") || !same_arg(5, "slashes" "\\\\" "\\\\")) return 15;
    if (mrl_io_argv(-1).ok || mrl_io_argv(argc).ok) return 3;
    value = mrl_io_read_utf8(%s);
    if (!value.ok || !same(value.value, "안녕\\nMRL")) return 4;
    mrl_io_string_release(value.value);
    missing = mrl_io_read_utf8(%s);
    if (missing.ok || !missing.error) return 5;
    invalid = mrl_io_read_utf8(%s);
    if (invalid.ok || !same(invalid.error, "io input is not valid UTF-8")) return 6;
    nul = mrl_io_read_utf8(%s);
    if (nul.ok || !same(nul.error, "io input contains NUL")) return 7;
    if (!mrl_io_write_utf8(%s, "새 값", &error) || error) return 8;
    value = mrl_io_read_utf8(%s);
    if (!value.ok || !same(value.value, "새 값")) return 9;
    mrl_io_string_release(value.value);
    { unsigned long process;
#if defined(_WIN32)
      process = (unsigned long)GetCurrentProcessId();
#else
      process = (unsigned long)getpid();
#endif
      char collision[4096];
      snprintf(collision, sizeof(collision), "%%s.mrl-tmp-%%lu-%%u", %s, process, mrl_io_temp_counter + 1);
      FILE *reserved = mrl_io_open(collision, "wb");
      if (!reserved) return 10;
      fputs("sentinel", reserved); fclose(reserved);
      if (!mrl_io_write_utf8(%s, "second", &error) || error) return 11;
      reserved = mrl_io_open(collision, "rb");
      char marker[9] = {0};
      if (!reserved || fread(marker, 1, 8, reserved) != 8 || fclose(reserved) != 0 || !same(marker, "sentinel")) return 12;
    }
    { const char bad[] = { 'x', (char)0xff, 0 };
      if (mrl_io_write_utf8(%s, bad, &error) || !same(error, "io input is not valid UTF-8")) return 13; }
    value = mrl_io_read_utf8(%s);
    if (!value.ok || !same(value.value, "second")) return 14;
    mrl_io_string_release(value.value);
    mrl_io_cleanup_argv();
    return 0;
}
""" % tuple(json.dumps(str(path).replace("\\", "/"), ensure_ascii=False) for path in (input_path, root / "missing.txt", invalid_path, nul_path, output_path, output_path, output_path, output_path, output_path, output_path))
            c_file, executable = root / "io.c", root / ("io.exe" if os.name == "nt" else "io")
            c_file.write_text(source, encoding="utf-8")
            try:
                build_c(c_file, executable)
            except subprocess.CalledProcessError as failure:
                self.fail((failure.stderr or b"").decode(errors="replace"))
            result = subprocess.run([str(executable), "인자🙂", "", 'a"b', "C:\\path with space\\", "slashes\\\\"], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
