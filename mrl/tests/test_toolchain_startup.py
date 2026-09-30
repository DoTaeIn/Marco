"""Build cache lookup must not launch an OS-version discovery subprocess."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mrl import toolchain


class ToolchainStartupTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows private compiler")
    def test_provisioned_compiler_does_not_scan_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiler = root / "zig-local" / "zig.exe"
            compiler.parent.mkdir()
            compiler.write_bytes(b"test")
            with mock.patch.object(toolchain, "_TOOLS", root), mock.patch.object(toolchain.shutil, "which", side_effect=AssertionError("unnecessary PATH scan")):
                command, shell = toolchain.find_compiler()
                self.assertEqual(command[0], str(compiler))
                self.assertFalse(shell)

    def test_identity_needs_no_subprocess_and_keeps_abi_in_cache_key(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "example.c"
            source.write_text("int main(void) { return 0; }", encoding="utf-8")
            with mock.patch.object(toolchain, "find_compiler", return_value=([sys.executable, "-std=c11"], False)), mock.patch.object(toolchain.subprocess, "run", side_effect=AssertionError("OS discovery subprocess")), mock.patch.object(toolchain.platform, "platform", side_effect=AssertionError("slow platform probe")), mock.patch.object(toolchain.platform, "machine", side_effect=AssertionError("slow machine probe")):
                first = toolchain.build_identity(source)
                self.assertEqual(first, toolchain.build_identity(source))
                with mock.patch.object(toolchain.sysconfig, "get_platform", return_value="different-abi"):
                    self.assertNotEqual(first["cache_key"], toolchain.build_identity(source)["cache_key"])
                self.assertNotEqual(first["cache_key"], toolchain.build_identity(source, optimization="debug")["cache_key"])
                source.write_text("int main(void) { return 1; }", encoding="utf-8")
                self.assertNotEqual(first["cache_key"], toolchain.build_identity(source)["cache_key"])


if __name__ == "__main__":
    unittest.main()
